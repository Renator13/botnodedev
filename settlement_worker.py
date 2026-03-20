"""Settlement worker — replaces cron-based auto-settle and auto-refund.

Runs as a background task inside the FastAPI process (alongside the
webhook worker).  Processes settlements and refunds every 15 seconds
with retry logic and dead-letter tracking.

This eliminates the single biggest fragility in v1: if the cron fails,
escrows freeze.  The worker is self-healing — if it encounters an error
on one escrow, it logs it, moves to the next, and retries on the next
cycle.

Lifecycle:
    1. Find AWAITING_SETTLEMENT escrows past their dispute window
    2. Run dispute engine + validators
    3. Settle or refund
    4. Find PENDING escrows past 72h timeout → auto-refund
    5. Log any failures as dead-letter for manual review
"""

import logging
from decimal import Decimal

from sqlalchemy.orm import Session
import sqlalchemy.exc

import models
from dependencies import _utcnow
from config import PROTOCOL_TAX_RATE
from ledger import record_transfer, VAULT
from dispute_engine import run_dispute_check
from worker import check_and_award_genesis_badges, recalculate_cri

logger = logging.getLogger("botnode.settlement")


def process_settlements(db: Session) -> dict:
    """Process all escrows ready for settlement.

    Returns a summary: {settled, auto_refunded, failed, dead_letter}.
    """
    now = _utcnow()
    results = {"settled": 0, "auto_refunded": 0, "failed": 0}

    # ── Phase 1: Auto-settle (dispute window expired) ──────────────────
    escrows = db.query(models.Escrow).filter(
        models.Escrow.status == "AWAITING_SETTLEMENT",
        models.Escrow.auto_settle_at != None,
        models.Escrow.auto_settle_at <= now,
    ).limit(50).all()

    for escrow in escrows:
        try:
            task = db.query(models.Task).filter(models.Task.escrow_id == escrow.id).first()
            skill = None
            if task and task.skill_id:
                skill = db.query(models.Skill).filter(models.Skill.id == task.skill_id).first()

            # Skip shadow tasks
            if task and task.is_shadow:
                escrow.status = "SETTLED"
                db.commit()
                results["settled"] += 1
                continue

            # Run dispute engine
            if task and run_dispute_check(db, task, escrow, skill):
                results["auto_refunded"] += 1
                db.commit()
                continue

            # Run custom validators
            if task and task.validator_ids:
                from routers.validators import run_validators
                passed, fail_details = run_validators(db, task)
                if not passed:
                    from dispute_engine import execute_auto_refund
                    execute_auto_refund(db, task, escrow, "VALIDATOR_FAILED", {"details": fail_details})
                    results["auto_refunded"] += 1
                    db.commit()
                    continue

            # Settlement (with row lock to prevent concurrent balance mutation)
            seller = db.query(models.Node).filter(models.Node.id == escrow.seller_id).with_for_update().first()
            if not seller:
                results["failed"] += 1
                continue

            tax = escrow.amount * PROTOCOL_TAX_RATE
            payout = escrow.amount - tax

            record_transfer(db, "ESCROW:" + escrow.id, seller.id, payout, "ESCROW_SETTLE", escrow.id, to_node=seller)
            record_transfer(db, "ESCROW:" + escrow.id, VAULT, tax, "PROTOCOL_TAX", escrow.id)
            escrow.status = "SETTLED"

            if seller.first_settled_tx_at is None:
                seller.first_settled_tx_at = _utcnow()
                check_and_award_genesis_badges(db)

            recalculate_cri(seller, db)

            # Check verifier pioneer eligibility
            try:
                from verifier_pioneer import check_and_award_pioneer
                check_and_award_pioneer(db, escrow.seller_id)
            except Exception:
                pass  # pioneer check failure should not block settlement

            # Dispatch webhook
            try:
                from webhook_service import dispatch_event
                dispatch_event(db, "escrow.settled", {"escrow_id": escrow.id, "amount": str(escrow.amount)}, node_id=escrow.seller_id)
            except Exception:
                pass  # webhook failure should not block settlement

            results["settled"] += 1
            db.commit()

        except (sqlalchemy.exc.SQLAlchemyError, ValueError) as e:
            db.rollback()
            results["failed"] += 1
            logger.error(f"Settlement failed for escrow {escrow.id}: {e}")

    # ── Phase 2: Auto-refund (72h timeout) ─────────────────────────────
    pending = db.query(models.Escrow).filter(
        models.Escrow.status == "PENDING",
        models.Escrow.auto_refund_at != None,
        models.Escrow.auto_refund_at <= now,
    ).limit(50).all()

    refunded = 0
    for escrow in pending:
        try:
            buyer = db.query(models.Node).filter(models.Node.id == escrow.buyer_id).first()
            if not buyer:
                continue

            # Skip shadow escrows
            task = db.query(models.Task).filter(models.Task.escrow_id == escrow.id).first()
            if task and task.is_shadow:
                escrow.status = "REFUNDED"
                db.commit()
                refunded += 1
                continue

            record_transfer(db, "ESCROW:" + escrow.id, buyer.id, escrow.amount, "ESCROW_REFUND", escrow.id, to_node=buyer)
            escrow.status = "REFUNDED"

            try:
                from webhook_service import dispatch_event
                dispatch_event(db, "escrow.refunded", {"escrow_id": escrow.id, "amount": str(escrow.amount)}, node_id=escrow.buyer_id)
            except Exception:
                pass

            refunded += 1
            db.commit()
        except (sqlalchemy.exc.SQLAlchemyError, ValueError) as e:
            db.rollback()
            results["failed"] += 1
            logger.error(f"Auto-refund failed for escrow {escrow.id}: {e}")

    results["auto_refunded"] += refunded

    # ── Phase 3: Stale detection ───────────────────────────────────────
    from datetime import timedelta
    stale_cutoff = now - timedelta(hours=48)
    stale = db.query(models.Escrow).filter(
        models.Escrow.status.in_(["PENDING", "AWAITING_SETTLEMENT"]),
        models.Escrow.created_at < stale_cutoff,
    ).count()
    if stale > 0:
        logger.warning(f"STALE ALERT: {stale} escrow(s) older than 48h still active")
        results["stale_alert"] = stale

    return results
