"""Admin endpoints: node sync, stats dashboard, and auto-settle cron."""

from decimal import Decimal
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
import sqlalchemy.exc

import models
import schemas
from dependencies import (
    audit_log, logger, _utcnow, get_db, verify_admin_token, require_admin_key,
)
from worker import check_and_award_genesis_badges, recalculate_cri
from config import PROTOCOL_TAX_RATE, PENDING_ESCROW_TIMEOUT
from ledger import record_transfer, VAULT, MINT
from dispute_engine import run_dispute_check

router = APIRouter(tags=["admin"])


@router.post("/api/v1/admin/sync/node")
def admin_sync_node(node_data: schemas.AdminNodeSync, request: Request, db: Session = Depends(get_db)) -> dict:
    """Create or update a node from an external admin source.

    Auth: ``BOTNODE_ADMIN_TOKEN`` via Bearer header.
    Upsert logic: if a node with the given ``id`` exists, non-protected
    fields are overwritten; otherwise a new row is inserted.  Financial
    fields (``balance``, ``reputation_score``) are coerced to ``Decimal``.
    """
    # Validate admin token
    admin_token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_admin_token(admin_token):
        raise HTTPException(status_code=401, detail="Admin authentication failed")

    data = node_data.model_dump(exclude_unset=True)

    # Check if the node already exists
    node = db.query(models.Node).filter(models.Node.id == data["id"]).first()

    if node:
        # Update existing node — balance mutations MUST go through the ledger
        for key, value in data.items():
            if key in ("id", "created_at", "balance"):
                continue  # C-02 fix: skip balance — use ledger endpoints instead
            if hasattr(node, key):
                if key == "reputation_score":
                    setattr(node, key, Decimal(str(value)))
                else:
                    setattr(node, key, value)
    else:
        # Create new node — balance must NOT be set directly (use ledger)
        processed_data = data.copy()
        processed_data.pop("balance", None)  # C-02 fix: never set balance via sync
        if "reputation_score" in processed_data:
            processed_data["reputation_score"] = Decimal(str(processed_data["reputation_score"]))
        # Parse created_at if provided, otherwise let the DB default handle it
        if "created_at" in processed_data:
            processed_data["created_at"] = datetime.fromisoformat(processed_data["created_at"])

        new_node = models.Node(**processed_data)
        db.add(new_node)

    db.commit()
    return {"status": "success", "node_id": data["id"]}


@router.get("/v1/admin/stats")
def get_admin_stats(period: str = "24h", _admin: bool = Depends(require_admin_key), db: Session = Depends(get_db)) -> dict:
    """Return platform metrics for the requested period.

    Auth: admin Bearer key.  Periods: ``24h``, ``7d``, ``30d``, or ``all``
    (since Genesis, 2026-01-01).  Includes node count, skill count, task
    count, transaction volume, and estimated vault tax (3 %).
    """
    now = _utcnow()
    if period == "24h":
        start_date = now - timedelta(days=1)
    elif period == "7d":
        start_date = now - timedelta(days=7)
    elif period == "30d":
        start_date = now - timedelta(days=30)
    else:
        start_date = datetime(2026, 1, 1) # Genesis

    node_count = db.query(models.Node).filter(models.Node.created_at >= start_date).count()
    skill_count = db.query(models.Skill).count() # Skills are persistent, but could filter if needed
    task_count = db.query(models.Task).filter(models.Task.created_at >= start_date).count()

    # Financials
    # Include both SETTLED and AWAITING_SETTLEMENT for volume transparency
    total_volume = db.query(func.sum(models.Escrow.amount)).filter(
        models.Escrow.status.in_(["SETTLED", "AWAITING_SETTLEMENT"]),
        models.Escrow.created_at >= start_date
    ).scalar() or 0

    vault_tax = str(Decimal(str(total_volume)) * PROTOCOL_TAX_RATE)

    return {
        "period": period,
        "metrics": {
            "total_nodes": node_count,
            "active_skills": skill_count,
            "tasks_processed": task_count,
            "transaction_volume": str(total_volume),
            "genesis_vault": vault_tax
        },
        "timestamp": now.isoformat()
    }


@router.post("/v1/admin/escrows/auto-settle")
def auto_settle_escrows(_admin: bool = Depends(require_admin_key), db: Session = Depends(get_db)) -> dict:
    """Automatically settle all escrows whose dispute window has expired.

    This is an internal/cron endpoint, protected by ADMIN_KEY via Authorization header.
    """

    now = _utcnow()
    escrows = db.query(models.Escrow).filter(
        models.Escrow.status == "AWAITING_SETTLEMENT",
        models.Escrow.auto_settle_at != None,
        models.Escrow.auto_settle_at <= now
    ).all()

    settled = 0
    auto_refunded = 0
    failed = 0
    total_tax = Decimal("0.0")

    for escrow in escrows:
        try:
            # Find the task and skill for dispute engine evaluation
            task = db.query(models.Task).filter(models.Task.escrow_id == escrow.id).first()
            skill = None
            if task and task.skill_id:
                skill = db.query(models.Skill).filter(models.Skill.id == task.skill_id).first()

            # Run dispute engine BEFORE settlement
            if task and run_dispute_check(db, task, escrow, skill):
                auto_refunded += 1
                db.commit()
                continue

            # Run custom validators (if any attached to the task)
            if task and task.validator_ids:
                from routers.validators import run_validators
                validators_passed, fail_details = run_validators(db, task)
                if not validators_passed:
                    from dispute_engine import execute_auto_refund
                    execute_auto_refund(db, task, escrow, "VALIDATOR_FAILED", {"details": fail_details})
                    auto_refunded += 1
                    db.commit()
                    continue

            seller = db.query(models.Node).filter(models.Node.id == escrow.seller_id).first()
            if not seller:
                failed += 1
                continue

            tax = escrow.amount * PROTOCOL_TAX_RATE
            payout = escrow.amount - tax

            record_transfer(db, "ESCROW:" + escrow.id, seller.id, payout, "ESCROW_SETTLE", escrow.id, to_node=seller)
            record_transfer(db, "ESCROW:" + escrow.id, VAULT, tax, "PROTOCOL_TAX", escrow.id)
            escrow.status = "SETTLED"
            from webhook_service import dispatch_event
            dispatch_event(db, "escrow.settled", {"escrow_id": escrow.id, "amount": str(escrow.amount)}, node_id=escrow.seller_id)

            if seller.first_settled_tx_at is None:
                seller.first_settled_tx_at = _utcnow()
                check_and_award_genesis_badges(db)

            recalculate_cri(seller, db)
            settled += 1
            total_tax += tax
            # Commit per-escrow so failures don't roll back the whole batch
            db.commit()
        except (sqlalchemy.exc.SQLAlchemyError, ValueError) as e:
            db.rollback()
            failed += 1
            logger.error(f"Auto-settle failed for escrow {escrow.id}: {e}")

    return {
        "status": "OK",
        "settled": settled,
        "auto_refunded": auto_refunded,
        "failed": failed,
        "tax_routed_to_vault": str(total_tax),
        "timestamp": now.isoformat()
    }


@router.post("/v1/admin/escrows/auto-refund")
def auto_refund_escrows(_admin: bool = Depends(require_admin_key), db: Session = Depends(get_db)) -> dict:
    """Refund PENDING escrows whose auto_refund_at deadline has passed.

    Escrows stuck in PENDING (i.e. the task was never completed) beyond
    the 72-hour timeout are automatically refunded to the buyer so that
    funds are not frozen indefinitely.

    Auth: admin Bearer key (``ADMIN_KEY`` env var).
    """
    now = _utcnow()
    escrows = db.query(models.Escrow).filter(
        models.Escrow.status == "PENDING",
        models.Escrow.auto_refund_at != None,
        models.Escrow.auto_refund_at <= now,
    ).all()

    count = 0
    for escrow in escrows:
        buyer = db.query(models.Node).filter(models.Node.id == escrow.buyer_id).first()
        if not buyer:
            continue
        record_transfer(db, "ESCROW:" + escrow.id, buyer.id, escrow.amount, "ESCROW_REFUND", escrow.id, to_node=buyer)
        escrow.status = "REFUNDED"
        from webhook_service import dispatch_event
        dispatch_event(db, "escrow.refunded", {"escrow_id": escrow.id, "amount": str(escrow.amount)}, node_id=escrow.buyer_id)
        count += 1

    db.commit()
    return {"status": "OK", "refunded": count}


@router.post("/v1/admin/disputes/resolve")
def resolve_dispute(
    escrow_id: str,
    resolution: str,
    _admin: bool = Depends(require_admin_key),
    db: Session = Depends(get_db),
) -> dict:
    """Resolve a disputed escrow by refunding the buyer or releasing funds to the seller.

    Auth: admin Bearer key.  Only escrows in DISPUTED state can be resolved.
    """
    escrow = db.query(models.Escrow).filter(models.Escrow.id == escrow_id).first()
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    if escrow.status != "DISPUTED":
        raise HTTPException(status_code=400, detail="Escrow is not in DISPUTED state")

    if resolution == "refund_buyer":
        buyer = db.query(models.Node).filter(models.Node.id == escrow.buyer_id).first()
        record_transfer(db, "ESCROW:" + escrow.id, buyer.id, escrow.amount, "DISPUTE_REFUND", escrow.id, to_node=buyer)
        escrow.status = "REFUNDED"
        from webhook_service import dispatch_event
        dispatch_event(db, "escrow.refunded", {"escrow_id": escrow.id, "amount": str(escrow.amount)}, node_id=escrow.buyer_id)
        db.commit()
        return {"status": "REFUNDED", "escrow_id": escrow_id, "amount": str(escrow.amount), "to": buyer.id}
    elif resolution == "release_to_seller":
        seller = db.query(models.Node).filter(models.Node.id == escrow.seller_id).first()
        tax = escrow.amount * PROTOCOL_TAX_RATE
        payout = escrow.amount - tax
        record_transfer(db, "ESCROW:" + escrow.id, seller.id, payout, "DISPUTE_RELEASE", escrow.id, to_node=seller)
        record_transfer(db, "ESCROW:" + escrow.id, VAULT, tax, "PROTOCOL_TAX", escrow.id)
        escrow.status = "SETTLED"
        from webhook_service import dispatch_event
        dispatch_event(db, "escrow.settled", {"escrow_id": escrow.id, "amount": str(escrow.amount)}, node_id=escrow.seller_id)
        db.commit()
        return {"status": "SETTLED", "escrow_id": escrow_id, "payout": str(payout), "tax": str(tax), "to": seller.id}
    else:
        raise HTTPException(status_code=400, detail="resolution must be 'refund_buyer' or 'release_to_seller'")


@router.post("/v1/admin/bounties/expire")
def expire_bounties(_admin: bool = Depends(require_admin_key), db: Session = Depends(get_db)) -> dict:
    """Expire open bounties whose deadline has passed and refund creators.

    This is an internal/cron endpoint, protected by ADMIN_KEY via Authorization header.
    Finds all open bounties with a deadline_at in the past, refunds the creator,
    and rejects all pending submissions.
    """
    now = _utcnow()
    bounties = db.query(models.Bounty).filter(
        models.Bounty.status == "open",
        models.Bounty.deadline_at != None,
        models.Bounty.deadline_at <= now,
    ).all()

    expired = 0
    failed = 0

    for bounty in bounties:
        try:
            creator = db.query(models.Node).filter(models.Node.id == bounty.creator_node_id).first()
            if not creator:
                failed += 1
                continue

            escrow_ref = bounty.escrow_reference or ("ESCROW:BOUNTY:" + bounty.id)
            record_transfer(db, escrow_ref, creator.id, bounty.reward_tck, "BOUNTY_REFUND", bounty.id, to_node=creator)

            bounty.status = "expired"
            bounty.cancelled_at = now

            # Reject all pending submissions
            pending_subs = db.query(models.BountySubmission).filter(
                models.BountySubmission.bounty_id == bounty.id,
                models.BountySubmission.status == "pending",
            ).all()
            for s in pending_subs:
                s.status = "rejected"
                s.reviewed_at = now

            expired += 1
            db.commit()
        except (sqlalchemy.exc.SQLAlchemyError, ValueError) as e:
            db.rollback()
            failed += 1
            logger.error(f"Bounty expire failed for {bounty.id}: {e}")

    return {
        "status": "OK",
        "expired": expired,
        "failed": failed,
        "timestamp": now.isoformat(),
    }


@router.get("/v1/admin/metrics")
def get_admin_metrics(_admin: bool = Depends(require_admin_key), db: Session = Depends(get_db)) -> dict:
    """Comprehensive business metrics for admin dashboard and investor meetings.

    Auth: admin Bearer key.  Returns aggregated KPIs across all time windows:
    tasks, settlements, GMV, nodes, skills, bounties.
    """
    now = _utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # Tasks
    total_tasks = db.query(func.count(models.Task.id)).scalar() or 0
    tasks_today = db.query(func.count(models.Task.id)).filter(models.Task.created_at >= today).scalar() or 0
    tasks_7d = db.query(func.count(models.Task.id)).filter(models.Task.created_at >= week_ago).scalar() or 0
    tasks_30d = db.query(func.count(models.Task.id)).filter(models.Task.created_at >= month_ago).scalar() or 0

    # Settlements
    total_settled = db.query(func.count(models.Escrow.id)).filter(models.Escrow.status == "SETTLED").scalar() or 0
    total_refunded = db.query(func.count(models.Escrow.id)).filter(models.Escrow.status == "REFUNDED").scalar() or 0
    total_disputed = db.query(func.count(models.Escrow.id)).filter(models.Escrow.status == "DISPUTED").scalar() or 0
    total_outcomes = total_settled + total_refunded + total_disputed
    settle_rate = round(total_settled / total_outcomes * 100, 1) if total_outcomes > 0 else 0
    dispute_rate = round(total_disputed / total_outcomes * 100, 1) if total_outcomes > 0 else 0

    # Auto-disputes
    auto_disputes = db.query(func.count(models.DisputeRulesLog.id)).scalar() or 0

    # GMV (Gross Merchandise Volume)
    total_tck = db.query(func.sum(models.Escrow.amount)).filter(
        models.Escrow.status.in_(["SETTLED", "AWAITING_SETTLEMENT"]),
    ).scalar() or Decimal("0")
    tck_7d = db.query(func.sum(models.Escrow.amount)).filter(
        models.Escrow.status.in_(["SETTLED", "AWAITING_SETTLEMENT"]),
        models.Escrow.created_at >= week_ago,
    ).scalar() or Decimal("0")
    tck_30d = db.query(func.sum(models.Escrow.amount)).filter(
        models.Escrow.status.in_(["SETTLED", "AWAITING_SETTLEMENT"]),
        models.Escrow.created_at >= month_ago,
    ).scalar() or Decimal("0")

    # Vault balance (sum of all PROTOCOL_TAX credits)
    vault_balance = db.query(func.sum(models.LedgerEntry.amount)).filter(
        models.LedgerEntry.account_id == "VAULT",
        models.LedgerEntry.entry_type == "CREDIT",
    ).scalar() or Decimal("0")

    # Nodes (exclude sandbox)
    total_nodes = db.query(func.count(models.Node.id)).filter(
        models.Node.is_sandbox == False
    ).scalar() or 0
    active_7d_sub = db.query(func.distinct(models.Escrow.buyer_id)).filter(
        models.Escrow.created_at >= week_ago,
    ).union(
        db.query(func.distinct(models.Escrow.seller_id)).filter(
            models.Escrow.created_at >= week_ago,
        )
    ).subquery()
    active_7d = db.query(func.count()).select_from(active_7d_sub).scalar() or 0

    genesis_filled = db.query(func.count(models.GenesisBadgeAward.id)).scalar() or 0

    # Skills
    total_skills = db.query(func.count(models.Skill.id)).scalar() or 0

    # Bounties
    total_bounties = db.query(func.count(models.Bounty.id)).scalar() or 0
    awarded_bounties = db.query(func.count(models.Bounty.id)).filter(
        models.Bounty.status == "awarded",
    ).scalar() or 0

    return {
        "generated_at": now.isoformat() + "Z",
        "tasks": {
            "total": total_tasks,
            "today": tasks_today,
            "last_7_days": tasks_7d,
            "last_30_days": tasks_30d,
        },
        "settlements": {
            "total_settled": total_settled,
            "total_refunded": total_refunded,
            "total_disputed": total_disputed,
            "settle_rate_pct": settle_rate,
            "dispute_rate_pct": dispute_rate,
            "auto_disputes": auto_disputes,
        },
        "gmv": {
            "total_tck_transacted": str(total_tck),
            "last_7_days_tck": str(tck_7d),
            "last_30_days_tck": str(tck_30d),
            "vault_balance": str(vault_balance),
        },
        "nodes": {
            "total_registered": total_nodes,
            "active_last_7_days": active_7d,
            "genesis_filled": genesis_filled,
            "genesis_total": 200,
        },
        "skills": {"total_published": total_skills},
        "bounties": {
            "total_created": total_bounties,
            "total_awarded": awarded_bounties,
        },
    }


@router.get("/v1/admin/ledger/reconcile")
def reconcile_ledger(_admin: bool = Depends(require_admin_key), db: Session = Depends(get_db)) -> dict:
    """Verify the fundamental ledger invariant: books must balance.

    Checks that MINT credits minus all VAULT credits equals the sum of
    all node balances.  Any discrepancy indicates a ledger bug.
    """
    total_minted = db.query(func.sum(models.LedgerEntry.amount)).filter(
        models.LedgerEntry.account_id == "MINT",
        models.LedgerEntry.entry_type == "DEBIT",
    ).scalar() or Decimal("0")

    vault_collected = db.query(func.sum(models.LedgerEntry.amount)).filter(
        models.LedgerEntry.account_id == "VAULT",
        models.LedgerEntry.entry_type == "CREDIT",
    ).scalar() or Decimal("0")

    # Production nodes only (exclude sandbox)
    real_balances = db.query(func.sum(models.Node.balance)).filter(
        models.Node.is_sandbox == False
    ).scalar() or Decimal("0")

    # All balances (including sandbox)
    total_balances = db.query(func.sum(models.Node.balance)).scalar() or Decimal("0")

    # Funds in active escrows (locked but not yet settled/refunded)
    escrow_locked = db.query(func.sum(models.Escrow.amount)).filter(
        models.Escrow.status.in_(["PENDING", "AWAITING_SETTLEMENT", "DISPUTED"]),
    ).scalar() or Decimal("0")

    # Funds locked in open bounties
    bounty_locked = db.query(func.sum(models.Bounty.reward_tck)).filter(
        models.Bounty.status == "open",
    ).scalar() or Decimal("0")

    # Full system reconciliation: every TCK must be accounted for
    # MINTED = node_balances + vault + active_escrows + active_bounties
    expected = total_minted
    actual = total_balances + vault_collected + escrow_locked + bounty_locked
    is_valid = abs(expected - actual) < Decimal("0.01")

    # ── Global conservation invariant ─────────────────────────────
    # The absolute value of the MINT balance (total ever minted) must
    # equal the sum of all node balances + all active escrow amounts
    # + the VAULT balance.  Any discrepancy indicates a ledger bug or
    # an unaccounted fund flow.
    #
    # MINT debits represent issuance; its "balance" is negative in a
    # double-entry system (contra-asset).  We use total_minted (sum
    # of MINT DEBIT entries) as the canonical issuance figure.
    conservation_sum = total_balances + escrow_locked + bounty_locked + vault_collected
    conservation_expected = total_minted
    conservation_discrepancy = conservation_sum - conservation_expected
    conservation_ok = abs(conservation_discrepancy) < Decimal("0.01")

    return {
        "valid": is_valid,
        "total_minted": str(total_minted),
        "total_in_wallets": str(total_balances),
        "total_in_vault": str(vault_collected),
        "total_in_escrow": str(escrow_locked),
        "total_in_bounties": str(bounty_locked),
        "sum_accounted": str(actual),
        "discrepancy": str(actual - expected),
        "conservation": {
            "valid": conservation_ok,
            "node_balances": str(total_balances),
            "active_escrows": str(escrow_locked),
            "active_bounties": str(bounty_locked),
            "vault_balance": str(vault_collected),
            "observed_total": str(conservation_sum),
            "mint_issued": str(conservation_expected),
            "discrepancy": str(conservation_discrepancy),
            "flag": None if conservation_ok else "CONSERVATION_VIOLATION: funds created or destroyed outside MINT",
        },
        "checked_at": _utcnow().isoformat() + "Z",
    }


@router.get("/v1/admin/disputes")
def list_disputes(
    reason: str = None,
    escrow_status: str = None,
    action: str = None,
    limit: int = 50,
    offset: int = 0,
    _admin: bool = Depends(require_admin_key),
    db: Session = Depends(get_db),
) -> dict:
    """List automated dispute decisions with optional filters.

    Auth: admin Bearer key.

    Query params:
        reason: SCHEMA_MISMATCH, TIMEOUT_NON_DELIVERY, or PROOF_MISSING
        escrow_status: filter by current escrow status (REFUNDED, SETTLED, etc.)
        action: AUTO_REFUND, AUTO_SETTLE, or FLAGGED_MANUAL
    """
    query = db.query(models.DisputeRulesLog).order_by(
        models.DisputeRulesLog.created_at.desc()
    )
    if reason:
        query = query.filter(models.DisputeRulesLog.rule_applied == reason)
    if action:
        query = query.filter(models.DisputeRulesLog.action_taken == action)
    if escrow_status:
        query = query.join(
            models.Escrow, models.DisputeRulesLog.escrow_id == models.Escrow.id
        ).filter(models.Escrow.status == escrow_status)

    total = query.count()
    entries = query.offset(offset).limit(limit).all()

    # Fetch escrow status for each entry
    escrow_ids = [e.escrow_id for e in entries]
    escrow_map = {}
    if escrow_ids:
        escrows = db.query(models.Escrow).filter(models.Escrow.id.in_(escrow_ids)).all()
        escrow_map = {esc.id: esc.status for esc in escrows}

    return {
        "disputes": [
            {
                "id": e.id,
                "task_id": e.task_id,
                "escrow_id": e.escrow_id,
                "escrow_status": escrow_map.get(e.escrow_id),
                "rule_applied": e.rule_applied,
                "rule_details": e.rule_details,
                "action_taken": e.action_taken,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/v1/admin/transactions")
def get_transactions(
    limit: int = 50,
    account: str = None,
    reference_type: str = None,
    _admin: bool = Depends(require_admin_key),
    db: Session = Depends(get_db),
) -> dict:
    """Return recent ledger entries for storytelling and audit.

    Auth: admin Bearer key.  Filterable by account and reference_type.
    Returns paired DEBIT+CREDIT entries in chronological order with
    human-readable narrative for each transaction.
    """
    query = db.query(models.LedgerEntry).order_by(
        models.LedgerEntry.created_at.desc()
    )
    if account:
        query = query.filter(models.LedgerEntry.account_id == account)
    if reference_type:
        query = query.filter(models.LedgerEntry.reference_type == reference_type)

    entries = query.limit(limit).all()

    NARRATIVES = {
        "REGISTRATION_CREDIT": "joined the Grid and received initial balance",
        "ESCROW_LOCK": "locked funds in escrow for a task",
        "ESCROW_SETTLE": "received payout from completed task",
        "ESCROW_REFUND": "received refund from expired escrow",
        "PROTOCOL_TAX": "protocol tax collected by the Grid",
        "LISTING_FEE": "paid listing fee to publish a skill",
        "CONFISCATION": "balance confiscated due to ban",
        "GENESIS_BONUS": "awarded Genesis badge bonus",
        "FIAT_PURCHASE": "purchased TCK with fiat",
        "CHARGEBACK_CLAWBACK": "TCK clawed back due to payment dispute",
        "REFUND_CLAWBACK": "TCK clawed back due to refund",
        "DISPUTE_REFUND": "refunded after dispute resolution",
        "DISPUTE_RELEASE": "released to seller after dispute resolution",
        "VERIFIER_PIONEER_BONUS": "Verifier Pioneer Program bonus — first 20 quality verifiers",
    }

    return {
        "entries": [
            {
                "id": e.id,
                "timestamp": e.created_at.isoformat() if e.created_at else None,
                "account": e.account_id,
                "type": e.entry_type,
                "amount": str(e.amount),
                "balance_after": str(e.balance_after) if e.balance_after is not None else None,
                "reference_type": e.reference_type,
                "reference_id": e.reference_id,
                "counterparty": e.counterparty_id,
                "note": e.note,
                "narrative": NARRATIVES.get(e.reference_type, e.reference_type),
            }
            for e in entries
        ],
        "count": len(entries),
    }


@router.get("/v1/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(_admin: bool = Depends(require_admin_key)) -> HTMLResponse:
    """Self-contained admin dashboard — single HTML page with fetch-based KPIs.

    Auth: admin Bearer key passed as ``?key=`` query param (the JS fetches
    use the same key for the API calls).
    """
    return HTMLResponse(content=_DASHBOARD_HTML)


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BotNode Admin Dashboard</title>
<style>
:root{--bg:#000;--s:#111;--b:#1e1e1e;--t:#bbb;--w:#f0f0f0;--cy:#00d4ff;--gn:#00e676;--am:#ffab00;--rd:#ff3d3d;--fm:'JetBrains Mono',monospace;--fs:'Space Grotesk',sans-serif}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--fs);background:var(--bg);color:var(--t);padding:2rem}
h1{font-family:var(--fm);font-size:1.5rem;color:var(--cy);margin-bottom:.5rem}
#status{font-family:var(--fm);font-size:12px;margin-bottom:1.5rem;color:#666}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem}
.card{background:var(--s);border:1px solid var(--b);border-radius:8px;padding:1.5rem}
.card h3{font-family:var(--fm);font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#666;margin-bottom:.5rem}
.value{font-size:2rem;font-weight:700;color:var(--w);font-family:var(--fm)}
.sub{font-size:11px;color:#555;font-family:var(--fm);margin-top:4px}
.ok{color:var(--gn)}.warn{color:var(--am)}.bad{color:var(--rd)}
#auth{margin-bottom:2rem}
#auth input{background:var(--s);border:1px solid var(--b);color:var(--t);padding:8px 12px;font-family:var(--fm);font-size:12px;width:300px;border-radius:4px}
#auth button{background:var(--cy);color:#000;border:none;padding:8px 16px;font-family:var(--fm);font-size:11px;font-weight:700;letter-spacing:1px;cursor:pointer;border-radius:4px;margin-left:8px}
</style>
</head>
<body>
<h1>BOTNODE DASHBOARD</h1>
<div id="auth">
<input type="password" id="key" placeholder="Admin API Key">
<button onclick="load()">LOAD</button>
</div>
<div id="status">Enter admin key and click Load</div>
<div class="grid" id="cards"></div>
<script>
async function load(){
 var k=document.getElementById('key').value;
 if(!k){document.getElementById('status').innerHTML='<span class="bad">Enter key</span>';return}
 var h={'Authorization':'Bearer '+k};
 try{
  var[m,r]=await Promise.all([
   fetch('/v1/admin/metrics',{headers:h}).then(function(x){return x.json()}),
   fetch('/v1/admin/ledger/reconcile',{headers:h}).then(function(x){return x.json()})
  ]);
  document.getElementById('status').innerHTML=
   '<span class="'+(r.valid?'ok':'bad')+'">Ledger: '+(r.valid?'Valid':'MISMATCH')+'</span> · '+m.generated_at;
  var c=document.getElementById('cards');c.innerHTML='';
  function card(t,v,s){return '<div class="card"><h3>'+t+'</h3><div class="value">'+v+'</div><div class="sub">'+(s||'')+'</div></div>'}
  c.innerHTML=
   card('Tasks Today',m.tasks.today,m.tasks.last_7_days+' last 7d')+
   card('Settle Rate',m.settlements.settle_rate_pct+'%',m.settlements.total_settled+' settled')+
   card('Dispute Rate',m.settlements.dispute_rate_pct+'%',m.settlements.total_disputed+' disputed')+
   card('Auto Disputes',m.settlements.auto_disputes,'automated refunds')+
   card('Active Nodes (7d)',m.nodes.active_last_7_days,m.nodes.total_registered+' total')+
   card('Genesis',m.nodes.genesis_filled+'/200','')+
   card('Skills',m.skills.total_published,'')+
   card('GMV (30d)',m.gmv.last_30_days_tck+' TCK',m.gmv.total_tck_transacted+' total')+
   card('Vault',m.gmv.vault_balance+' TCK','')+
   card('Bounties',m.bounties.total_created,m.bounties.total_awarded+' awarded')+
   card('Discrepancy',r.discrepancy+' TCK','<span class="'+(r.valid?'ok':'bad')+'">'+(r.valid?'Balanced':'CHECK')+'</span>');
 }catch(e){document.getElementById('status').innerHTML='<span class="bad">Error: '+e.message+'</span>'}
}
</script>
</body>
</html>"""
