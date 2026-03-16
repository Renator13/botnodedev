"""Trade, escrow, and task endpoints."""

from decimal import Decimal
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

import models
import schemas
from dependencies import (
    audit_log, _utcnow, get_db, get_node, get_current_node,
)
from worker import check_and_award_genesis_badges, recalculate_cri
from config import PROTOCOL_TAX_RATE, DISPUTE_WINDOW, PENDING_ESCROW_TIMEOUT
from ledger import record_transfer, VAULT

router = APIRouter(tags=["escrow"])


@router.post("/v1/trade/escrow/init")
def init_escrow(data: schemas.EscrowInit, buyer: models.Node = Depends(get_current_node), db: Session = Depends(get_db)) -> dict:
    """Lock buyer funds in a new PENDING escrow.

    Auth: JWT or API key.  The buyer's row is locked with ``SELECT FOR UPDATE``
    to prevent double-spend under concurrent requests.  The escrow starts in
    ``PENDING`` state and must transition to ``AWAITING_SETTLEMENT`` via task
    completion before it can be settled.
    """
    # Idempotency check
    if data.idempotency_key:
        existing = db.query(models.Escrow).filter(models.Escrow.idempotency_key == data.idempotency_key).first()
        if existing:
            return {"escrow_id": existing.id, "status": "FUNDS_LOCKED", "idempotent": True}

    # Lock the buyer row to prevent double-spend race conditions
    buyer = db.query(models.Node).filter(models.Node.id == buyer.id).with_for_update().first()
    amount = Decimal(str(data.amount))
    if buyer.balance < amount:
        raise HTTPException(status_code=402, detail="Insufficient funds")

    new_escrow = models.Escrow(
        buyer_id=buyer.id,
        seller_id=data.seller_id,
        amount=data.amount,
        status="PENDING",
        auto_refund_at=_utcnow() + PENDING_ESCROW_TIMEOUT,
        idempotency_key=data.idempotency_key,
    )
    db.add(new_escrow)
    db.flush()
    record_transfer(db, buyer.id, "ESCROW:" + new_escrow.id, amount, "ESCROW_LOCK", new_escrow.id, from_node=buyer)
    db.commit()

    return {"escrow_id": new_escrow.id, "status": "FUNDS_LOCKED"}


@router.post("/v1/trade/escrow/settle")
def settle_escrow(data: schemas.EscrowSettle, caller: models.Node = Depends(get_current_node), db: Session = Depends(get_db)) -> dict:
    """Settle an escrow after the 24-hour dispute window has closed.

    Auth: JWT or API key.  Only the buyer or seller of the escrow may call
    this endpoint.  Settlement is blocked if:
    - The escrow is not in ``AWAITING_SETTLEMENT`` state.
    - ``auto_settle_at`` has not yet passed (dispute window still open).

    On success: seller receives ``amount - 3% tax``, CRI is recalculated,
    and the Genesis badge worker is triggered if this is the seller's first
    settled transaction.
    """
    escrow = db.query(models.Escrow).filter(models.Escrow.id == data.escrow_id).first()
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")

    # C-03 fix: verify caller is buyer or seller of this escrow
    if caller.id not in (escrow.buyer_id, escrow.seller_id):
        raise HTTPException(status_code=403, detail="Not a party to this escrow")

    # Enforce FSM: only allow settlement from AWAITING_SETTLEMENT
    if escrow.status not in ["AWAITING_SETTLEMENT"]:
        raise HTTPException(status_code=400, detail="Escrow not ready for settlement")

    # Enforce dispute window: cannot settle before auto_settle_at
    if escrow.auto_settle_at and _utcnow() < escrow.auto_settle_at:
        raise HTTPException(
            status_code=400,
            detail=f"Dispute window open until {escrow.auto_settle_at.isoformat()}Z"
        )

    # 4. Calculate Tax (3%)
    tax = escrow.amount * PROTOCOL_TAX_RATE
    payout = escrow.amount - tax

    # 5. Transfer to Seller via ledger
    seller = db.query(models.Node).filter(models.Node.id == escrow.seller_id).first()
    record_transfer(db, "ESCROW:" + escrow.id, seller.id, payout, "ESCROW_SETTLE", escrow.id, to_node=seller)
    record_transfer(db, "ESCROW:" + escrow.id, VAULT, tax, "PROTOCOL_TAX", escrow.id)

    # Mark escrow as settled
    escrow.status = "SETTLED"
    escrow.proof_hash = data.proof_hash

    # Genesis program hook: capture seller's first settled transaction
    if seller.first_settled_tx_at is None:
        seller.first_settled_tx_at = _utcnow()
        check_and_award_genesis_badges(db)

    # Recalculate seller CRI after settlement
    recalculate_cri(seller, db)

    db.commit()

    return {"status": "SETTLED", "payout": payout, "tax": tax}


@router.post("/v1/tasks/create")
def create_task(data: schemas.TaskCreate, buyer: models.Node = Depends(get_node), db: Session = Depends(get_db)) -> dict:
    """Create a task and auto-lock funds in escrow.

    Auth: API key.  Atomically deducts the skill price from the buyer's
    balance (row-locked), creates a PENDING escrow, and opens an OPEN task
    assigned to the skill's provider.
    """
    skill = db.query(models.Skill).filter(models.Skill.id == data.skill_id).first()
    if not skill: raise HTTPException(status_code=404, detail="Skill not found")

    # Idempotency check
    if data.idempotency_key:
        existing = db.query(models.Escrow).filter(models.Escrow.idempotency_key == data.idempotency_key).first()
        if existing:
            task = db.query(models.Task).filter(models.Task.escrow_id == existing.id).first()
            return {"task_id": task.id if task else None, "escrow_id": existing.id, "status": "QUEUED", "idempotent": True}

    # Lock buyer row to prevent double-spend
    buyer = db.query(models.Node).filter(models.Node.id == buyer.id).with_for_update().first()
    if buyer.balance < skill.price_tck:
        raise HTTPException(status_code=402, detail="Insufficient funds")
    new_escrow = models.Escrow(
        buyer_id=buyer.id,
        seller_id=skill.provider_id,
        amount=skill.price_tck,
        status="PENDING",
        auto_refund_at=_utcnow() + PENDING_ESCROW_TIMEOUT,
        idempotency_key=data.idempotency_key,
    )
    db.add(new_escrow)
    db.flush()
    record_transfer(db, buyer.id, "ESCROW:" + new_escrow.id, Decimal(str(skill.price_tck)), "ESCROW_LOCK", new_escrow.id, from_node=buyer)

    new_task = models.Task(
        skill_id=data.skill_id,
        buyer_id=buyer.id,
        seller_id=skill.provider_id,
        input_data=data.input_data,
        status="OPEN",
        escrow_id=new_escrow.id
    )
    db.add(new_task)
    db.commit()

    return {"task_id": new_task.id, "escrow_id": new_escrow.id, "status": "QUEUED"}


@router.post("/v1/tasks/complete")
def complete_task(data: schemas.TaskComplete, seller: models.Node = Depends(get_node), db: Session = Depends(get_db)) -> dict:
    """Mark a task as completed and open the 24-hour dispute window.

    Auth: API key (seller only).  Transitions the task from OPEN to COMPLETED
    and the escrow from PENDING to AWAITING_SETTLEMENT with ``auto_settle_at``
    set 24 hours in the future.
    """
    task = db.query(models.Task).filter(models.Task.id == data.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.seller_id != seller.id:
        raise HTTPException(status_code=403, detail="Not your task")

    # FSM: only OPEN tasks can be completed
    if task.status != "OPEN":
        raise HTTPException(status_code=400, detail="Task cannot be completed from current state")

    # Update Task
    task.output_data = data.output_data
    task.status = "COMPLETED"

    # Schedule Settle Escrow (24h Window for Disputes)
    escrow = db.query(models.Escrow).filter(models.Escrow.id == task.escrow_id).first()
    escrow.status = "AWAITING_SETTLEMENT"
    escrow.auto_settle_at = _utcnow() + DISPUTE_WINDOW
    escrow.proof_hash = data.proof_hash

    db.commit()
    return {
        "status": "COMPLETED",
        "settlement_status": "PENDING_DISPUTE_WINDOW",
        "eta_tck_release": escrow.auto_settle_at.isoformat()
    }


@router.post("/v1/tasks/dispute")
def dispute_task(data: schemas.DisputeRequest, buyer: models.Node = Depends(get_node), db: Session = Depends(get_db)) -> dict:
    """Dispute a completed task, freezing escrow funds.

    Auth: API key (buyer only).  Can only be called while the escrow is in
    ``AWAITING_SETTLEMENT``.  Transitions both the task and escrow to
    ``DISPUTED`` state, blocking automatic settlement until manual review.
    """
    task = db.query(models.Task).filter(models.Task.id == data.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.buyer_id != buyer.id:
        raise HTTPException(status_code=403, detail="Not your task")

    # FSM: only COMPLETED tasks, awaiting settlement, can be disputed
    if task.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="Cannot dispute task from current state")

    escrow = db.query(models.Escrow).filter(models.Escrow.id == task.escrow_id).first()
    if escrow.status != "AWAITING_SETTLEMENT":
        raise HTTPException(status_code=400, detail="Cannot dispute: Task not completed or already settled")

    escrow.status = "DISPUTED"
    task.status = "DISPUTED"
    db.commit()

    return {"status": "DISPUTE_OPEN", "message": "Funds frozen. Manual node audit initiated."}
