"""Background worker functions for BotNode.

Contains CRI (Cryptographic Reliability Index) recalculation, Genesis badge
awarding logic, and related helper utilities that run outside the request
cycle.
"""

import logging
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from config import (
    MAX_GENESIS_BADGES, GENESIS_BONUS_TCK, GENESIS_PROTECTION_WINDOW, GENESIS_CRI_FLOOR,
)
from ledger import record_transfer, MINT

logger = logging.getLogger("botnode.worker")


def _utcnow():
    """Return the current UTC time as a naive datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def recalculate_cri(node: models.Node, db: Session) -> float:
    """Recalculate CRI for a node based on real on-chain activity.

    Factors (0-100 scale):
    - Settled transactions as seller (weight: 30) — max at 20 tx
    - Account age in days (weight: 15) — max at 90 days
    - Dispute rate as seller (weight: -25) — disputes / total tasks
    - Strike penalty (weight: -15 per strike)
    - Genesis badge bonus (weight: +10)
    """
    now = _utcnow()

    # Settled TX count as seller
    settled_count = db.query(models.Escrow).filter(
        models.Escrow.seller_id == node.id,
        models.Escrow.status == "SETTLED",
    ).count()
    tx_score = min(30.0, (settled_count / 20.0) * 30.0)

    # Account age
    age_days = max(0, (now - node.created_at).days) if node.created_at else 0
    age_score = min(15.0, (age_days / 90.0) * 15.0)

    # Dispute rate as seller
    total_tasks_as_seller = db.query(models.Task).filter(
        models.Task.seller_id == node.id,
        models.Task.status.in_(["COMPLETED", "DISPUTED"]),
    ).count()
    disputed_tasks = db.query(models.Task).filter(
        models.Task.seller_id == node.id,
        models.Task.status == "DISPUTED",
    ).count()
    if total_tasks_as_seller > 0:
        dispute_penalty = (disputed_tasks / total_tasks_as_seller) * 25.0
    else:
        dispute_penalty = 0.0

    # Strike penalty
    strike_penalty = node.strikes * 15.0

    # Genesis bonus
    genesis_bonus = 10.0 if node.has_genesis_badge else 0.0

    # Base score starts at 50 (neutral)
    raw = 50.0 + tx_score + age_score - dispute_penalty - strike_penalty + genesis_bonus
    cri = max(0.0, min(100.0, round(raw, 1)))

    # Apply Genesis CRI floor
    if node.has_genesis_badge and node.first_settled_tx_at and node.strikes < 3:
        protection_end = node.first_settled_tx_at + GENESIS_PROTECTION_WINDOW
        if now <= protection_end and cri < GENESIS_CRI_FLOOR:
            cri = GENESIS_CRI_FLOOR

    node.cri_score = cri
    node.cri_updated_at = now
    return cri


def apply_cri_floor(node: models.Node) -> None:  # noqa: D401
    """Apply the 'CRI Floor 1.0' logic for Genesis Nodes.

    Rule: If a node has a Genesis Badge, its reputation score cannot drop below 1.0
    for 180 days after its first settled transaction, unless explicitly slashed
    (strikes >= 3).

    This function should be called whenever reputation_score is updated.
    """
    if not node.has_genesis_badge or not node.first_settled_tx_at:
        return

    # Check if within protection window
    if _utcnow() <= (node.first_settled_tx_at + GENESIS_PROTECTION_WINDOW):
        # Apply floor only if not banned (strikes < 3)
        if node.strikes < 3 and node.reputation_score < GENESIS_CRI_FLOOR:
            node.reputation_score = GENESIS_CRI_FLOOR


def check_and_award_genesis_badges(db: Session) -> None:
    """Evaluate eligible nodes and assign Genesis badges.

    This worker is invoked from settlement paths once a node records its
    first SETTLED transaction. It is designed to be **idempotent** and
    safe to call multiple times within the same process.

    Rules (summarized):
    - Only the first 200 nodes can receive a Genesis badge.
    - Eligibility: node has a non-null `first_settled_tx_at`, is linked
      via `signup_token`, and does not yet have `has_genesis_badge` set.
    - Ranking is determined by `first_settled_tx_at` (ascending).
    - Awarding a badge:
      - Set `has_genesis_badge = True`.
      - Set `genesis_rank` to the assigned rank (1..200).
      - Add 300 TCK to the node balance.
      - Insert a row into `genesis_badge_awards`.

    The caller is responsible for committing the transaction; this
    function will only `flush()` the session so that inserts/updates are
    visible within the current transaction.
    """

    logger.info("Checking for Genesis badges...")

    # 1) How many Genesis badges have already been awarded?
    current_count = (
        db.query(models.Node)
        .filter(models.Node.has_genesis_badge.is_(True))
        .count()
    )

    if current_count >= MAX_GENESIS_BADGES:
        # Nothing to do; cap already reached.
        logger.info(
            "%d badges already awarded; no slots remaining.", current_count
        )
        return

    slots_remaining = MAX_GENESIS_BADGES - current_count

    # 2) Find eligible nodes that do NOT yet have a Genesis badge.
    #    Conditions:
    #      - first_settled_tx_at IS NOT NULL
    #      - has_genesis_badge IS FALSE
    #      - signup_token IS NOT NULL (linked to early access)
    #    Ordered by first_settled_tx_at ASC to respect true arrival order.
    eligible_nodes = (
        db.query(models.Node)
        .filter(
            models.Node.first_settled_tx_at.isnot(None),
            models.Node.has_genesis_badge.is_(False),
            models.Node.signup_token.isnot(None),
        )
        .order_by(models.Node.first_settled_tx_at.asc())
        .limit(slots_remaining)
        .all()
    )

    if not eligible_nodes:
        logger.info("No eligible nodes found for Genesis badges.")
        return

    # 3) Award badges to the first N eligible nodes within the remaining slots.
    for idx, node in enumerate(eligible_nodes, start=1):
        rank = current_count + idx

        # Safety guard: should not happen due to LIMIT, but keep it robust.
        if rank > MAX_GENESIS_BADGES:
            break

        # Update Node state.
        node.has_genesis_badge = True
        node.genesis_rank = rank

        # Balance is a Numeric/Decimal; ensure we add a Decimal amount via ledger.
        record_transfer(db, MINT, node.id, GENESIS_BONUS_TCK, "GENESIS_BONUS", str(node.id), to_node=node)
        
        # Apply CRI floor immediately upon getting badge
        apply_cri_floor(node)

        # Create log entry in GenesisBadgeAward table.
        award = models.GenesisBadgeAward(
            node_id=node.id,
            genesis_rank=rank,
            # awarded_at uses default timestamp
            # first_tx_id / badge_url can be filled later by other workers
        )
        db.add(award)

        logger.info("Awarded Genesis Badge #%d to node %s", rank, node.id)

    # Ensure all changes are pushed to the DB within the current
    # transaction. The outer caller is expected to commit.
    db.flush()
