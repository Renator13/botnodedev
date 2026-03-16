"""Admin endpoints: node sync, stats dashboard, and auto-settle cron."""

from decimal import Decimal
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, HTTPException, Depends
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
from ledger import record_transfer, VAULT

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
        # Update existing node
        for key, value in data.items():
            if hasattr(node, key) and key != "id" and key != "created_at":
                if key == "balance" or key == "reputation_score":
                    setattr(node, key, Decimal(str(value)))
                else:
                    setattr(node, key, value)
    else:
        # Create new node — convert JSON floats to Decimal for the DB
        processed_data = data.copy()
        if "balance" in processed_data:
            processed_data["balance"] = Decimal(str(processed_data["balance"]))
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
    failed = 0
    total_tax = Decimal("0.0")

    for escrow in escrows:
        try:
            seller = db.query(models.Node).filter(models.Node.id == escrow.seller_id).first()
            if not seller:
                failed += 1
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
        db.commit()
        return {"status": "REFUNDED", "escrow_id": escrow_id, "amount": str(escrow.amount), "to": buyer.id}
    elif resolution == "release_to_seller":
        seller = db.query(models.Node).filter(models.Node.id == escrow.seller_id).first()
        tax = escrow.amount * PROTOCOL_TAX_RATE
        payout = escrow.amount - tax
        record_transfer(db, "ESCROW:" + escrow.id, seller.id, payout, "DISPUTE_RELEASE", escrow.id, to_node=seller)
        record_transfer(db, "ESCROW:" + escrow.id, VAULT, tax, "PROTOCOL_TAX", escrow.id)
        escrow.status = "SETTLED"
        db.commit()
        return {"status": "SETTLED", "escrow_id": escrow_id, "payout": str(payout), "tax": str(tax), "to": seller.id}
    else:
        raise HTTPException(status_code=400, detail="resolution must be 'refund_buyer' or 'release_to_seller'")
