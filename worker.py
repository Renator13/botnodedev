"""Background worker functions for BotNode.

Contains CRI (Composite Reliability Index) recalculation, Genesis badge
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
    """Recalculate CRI (Composite Reliability Index) for a node.

    The CRI is a 0-100 score computed from on-chain activity.  It uses
    logarithmic scaling (diminishing returns) and Sybil-resistant factors
    (counterparty diversity, concentration penalty) to make gaming
    expensive.

    **Positive factors** (max 100 combined):

    =================  ======  ==========================================
    Factor             Weight  Rationale
    =================  ======  ==========================================
    Base               30      Every active node starts credible
    Transaction score  20      log2(settled+1), caps at ~64 TX
    Diversity score    15      Unique counterparties / total TX ratio
    Volume score       10      log10(total_tck_settled+1), caps at 10k
    Age score          10      log2(days+1), caps at ~256 days
    Buyer activity      5      Has the node also bought? (not just sold)
    Genesis bonus      10      Genesis badge holders
    =================  ======  ==========================================

    **Negative factors** (uncapped):

    ========================  ==========================================
    Factor                    Rationale
    ========================  ==========================================
    Dispute penalty (0-25)    disputes / total_tasks as seller
    Concentration penalty     >50% trades with same node = Sybil signal
    Strike penalty (15 each)  Hard penalty per malfeasance report
    ========================  ==========================================

    A Sybil attacker creating 10 nodes and ring-trading between them
    gets penalized by: low diversity score (few unique counterparties),
    high concentration penalty (>50% with same nodes), and logarithmic
    TX scaling (100 fake trades ≈ same score as 7 real ones).

    **Academic foundations:**

    Each factor is grounded in published research:

    - Log scaling: Weber-Fechner Law (1860); EigenTrust (Kamvar et al.,
      Stanford, 2003 — WWW Test of Time Award 2019) proved linear scaling
      is vulnerable to volume farming.
    - Diversity: Douceur (Microsoft Research, 2002) proved Sybil attacks
      are inevitable but can be made economically inviable. Cheng &
      Friedman (2005) proved systems without diversity penalties are
      Sybil-exploitable.
    - Age: Resnick & Zeckhauser (Harvard/Michigan, 2002) established
      empirically with eBay data that seller tenure predicts behavior.
      Time is the only non-forgeable factor.
    - Base score: Schein et al. (2002) on cold-start; EigenTrust
      "pre-trusted peers" — zero-scored new users create death spirals.
    - Dispute penalty: Ostrom (Nobel 2009) — graduated sanctions. Axelrod
      (1984) — tit-for-tat as dominant strategy in iterated games.
    - Concentration: Herfindahl-Hirschman Index (1945), used by DOJ/EC
      for market concentration.
    - Portability: Resnick et al. (2000); W3C Verifiable Credentials
      (2019).
    - Systemic resistance: Margolin & Levine (2008); Shi (2025)
      "Sybil-Resistant Service Discovery for Agent Economies."

    Coefficients are hypotheses; architecture is consensus. See Section
    8.3 of the whitepaper for full citations.
    """
    import math
    now = _utcnow()

    # ── Positive: Transaction score (logarithmic, caps ~64 TX) ───────
    settled_as_seller = db.query(models.Escrow).filter(
        models.Escrow.seller_id == node.id,
        models.Escrow.status == "SETTLED",
    ).count()
    settled_as_buyer = db.query(models.Escrow).filter(
        models.Escrow.buyer_id == node.id,
        models.Escrow.status == "SETTLED",
    ).count()
    total_settled = settled_as_seller + settled_as_buyer
    tx_score = min(20.0, math.log2(total_settled + 1) * 3.33)

    # ── Positive: Counterparty diversity (Sybil-resistant) ───────────
    # Unique nodes this node has traded with (as buyer or seller)
    seller_counterparties = db.query(models.Escrow.buyer_id).filter(
        models.Escrow.seller_id == node.id,
        models.Escrow.status == "SETTLED",
    ).distinct().count()
    buyer_counterparties = db.query(models.Escrow.seller_id).filter(
        models.Escrow.buyer_id == node.id,
        models.Escrow.status == "SETTLED",
    ).distinct().count()
    unique_counterparties = seller_counterparties + buyer_counterparties
    if total_settled > 0:
        diversity_ratio = min(1.0, unique_counterparties / max(1, total_settled))
        diversity_score = diversity_ratio * 15.0
    else:
        diversity_score = 0.0

    # ── Positive: Volume score (logarithmic, caps at ~10k TCK) ───────
    from sqlalchemy import func as sqlfunc
    total_volume = db.query(
        sqlfunc.coalesce(sqlfunc.sum(models.Escrow.amount), 0)
    ).filter(
        (models.Escrow.seller_id == node.id) | (models.Escrow.buyer_id == node.id),
        models.Escrow.status == "SETTLED",
    ).scalar()
    volume_score = min(10.0, math.log10(float(total_volume) + 1) * 2.5)

    # ── Positive: Account age (logarithmic, caps at ~256 days) ───────
    age_days = max(0, (now - node.created_at).days) if node.created_at else 0
    age_score = min(10.0, math.log2(age_days + 1) * 1.25)

    # ── Positive: Buyer activity (not just seller) ───────────────────
    buyer_score = 5.0 if settled_as_buyer > 0 else 0.0

    # ── Positive: Genesis bonus ──────────────────────────────────────
    genesis_bonus = 10.0 if node.has_genesis_badge else 0.0

    # ── Negative: Dispute rate as seller ─────────────────────────────
    total_tasks_as_seller = db.query(models.Task).filter(
        models.Task.seller_id == node.id,
        models.Task.status.in_(["COMPLETED", "DISPUTED"]),
    ).count()
    disputed_tasks = db.query(models.Task).filter(
        models.Task.seller_id == node.id,
        models.Task.status == "DISPUTED",
    ).count()
    dispute_penalty = (disputed_tasks / total_tasks_as_seller * 25.0) if total_tasks_as_seller > 0 else 0.0

    # ── Negative: Concentration penalty (Sybil detection) ────────────
    # If >50% of trades are with the same counterparty = suspicious
    concentration_penalty = 0.0
    if total_settled >= 5:
        # Find the most frequent counterparty
        from sqlalchemy import case, literal_column
        top_seller = db.query(
            models.Escrow.seller_id, sqlfunc.count().label("cnt")
        ).filter(
            models.Escrow.buyer_id == node.id,
            models.Escrow.status == "SETTLED",
        ).group_by(models.Escrow.seller_id).order_by(sqlfunc.count().desc()).first()

        top_buyer = db.query(
            models.Escrow.buyer_id, sqlfunc.count().label("cnt")
        ).filter(
            models.Escrow.seller_id == node.id,
            models.Escrow.status == "SETTLED",
        ).group_by(models.Escrow.buyer_id).order_by(sqlfunc.count().desc()).first()

        max_with_single = max(
            top_seller[1] if top_seller else 0,
            top_buyer[1] if top_buyer else 0,
        )
        concentration_ratio = max_with_single / total_settled
        if concentration_ratio > 0.5:
            concentration_penalty = (concentration_ratio - 0.5) * 20.0  # up to 10 points

    # ── Negative: Strike penalty ─────────────────────────────────────
    strike_penalty = node.strikes * 15.0

    # ── Final score ──────────────────────────────────────────────────
    raw = (
        30.0                    # base
        + tx_score              # 0-20 (log)
        + diversity_score       # 0-15 (Sybil-resistant)
        + volume_score          # 0-10 (log)
        + age_score             # 0-10 (log)
        + buyer_score           # 0-5
        + genesis_bonus         # 0-10
        - dispute_penalty       # 0-25
        - concentration_penalty # 0-10
        - strike_penalty        # 15 per strike
    )
    cri = max(0.0, min(100.0, round(raw, 1)))

    # ── Temporal decay: inactivity penalty ────────────────────────
    # If a node has had no settled transactions in the last 90 days,
    # the CRI starts decaying linearly.  After 90 days of inactivity
    # the score loses up to 50% over the following year (365 days),
    # clamped so the decay factor never goes below 0.5.
    # Rationale: stale reputations should not carry full weight —
    # a node that hasn't traded recently is an unknown quantity.
    last_settled = db.query(func.max(models.Escrow.created_at)).filter(
        (models.Escrow.seller_id == node.id) | (models.Escrow.buyer_id == node.id),
        models.Escrow.status == "SETTLED",
    ).scalar()
    if last_settled:
        days_since_last_trade = (now - last_settled).days
        if days_since_last_trade > 90:
            decay_factor = max(0.5, 1.0 - (days_since_last_trade - 90) / 365.0)
            cri = max(0.0, round(cri * decay_factor, 1))

    # Apply Genesis CRI floor
    if node.has_genesis_badge and node.first_settled_tx_at and node.strikes < 3:
        protection_end = node.first_settled_tx_at + GENESIS_PROTECTION_WINDOW
        if now <= protection_end and cri < GENESIS_CRI_FLOOR:
            cri = GENESIS_CRI_FLOOR

    node.cri_score = cri
    node.cri_updated_at = now
    return cri


def apply_cri_floor(node: models.Node) -> None:  # noqa: D401
    """Apply the CRI Floor logic for Genesis Nodes.

    Rule: If a node has a Genesis Badge, its reputation score cannot drop below
    GENESIS_CRI_FLOOR (30.0) for 180 days after its first settled transaction,
    unless explicitly slashed (strikes >= 3).

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
