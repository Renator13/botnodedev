"""Trade, escrow, and task endpoints."""

import hashlib
import json
import unicodedata
from decimal import Decimal
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

import models
import schemas
from dependencies import (
    audit_log, _utcnow, get_db, get_node, get_current_node,
    enforce_node_rate_limit,
)
from worker import check_and_award_genesis_badges, recalculate_cri
from config import PROTOCOL_TAX_RATE, DISPUTE_WINDOW, PENDING_ESCROW_TIMEOUT
from ledger import record_transfer, VAULT


def canonical_proof_hash(data: dict) -> str:
    """Generate a canonical SHA-256 proof hash from a dict.

    Canonicalization guarantees deterministic hashing regardless of key
    insertion order or platform-specific encoding differences:

    1. ``json.dumps`` with ``sort_keys=True`` and compact separators
       to eliminate key-order and whitespace variance.
    2. ``ensure_ascii=False`` so non-ASCII is preserved as-is.
    3. Unicode NFC normalization so that equivalent codepoint sequences
       (e.g. ``e + combining-acute`` vs. ``é``) produce identical bytes.
    4. UTF-8 encoding before SHA-256.
    """
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    normalized = unicodedata.normalize("NFC", serialized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

router = APIRouter(tags=["escrow"])


@router.post("/v1/trade/escrow/init", dependencies=[Depends(enforce_node_rate_limit)])
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

    # C-01 fix: Sandbox isolation — prevent fake TCK from entering real economy
    seller_node = db.query(models.Node).filter(models.Node.id == data.seller_id).first()
    if buyer.is_sandbox and seller_node and not seller_node.is_sandbox and data.seller_id not in ("botnode-official", "house"):
        raise HTTPException(status_code=403, detail="Sandbox nodes cannot trade with production nodes")
    if not buyer.is_sandbox and seller_node and seller_node.is_sandbox:
        raise HTTPException(status_code=403, detail="Production nodes cannot trade with sandbox nodes")

    # Prevent self-trade (wash trading)
    if buyer.id == data.seller_id:
        raise HTTPException(status_code=400, detail="Self-trade not allowed")

    # Lock the buyer row to prevent double-spend race conditions
    buyer = db.query(models.Node).filter(models.Node.id == buyer.id).with_for_update().first()
    amount = Decimal(str(data.amount))
    if buyer.balance < amount:
        raise HTTPException(status_code=402, detail="Insufficient funds")

    new_escrow = models.Escrow(
        buyer_id=buyer.id,
        seller_id=data.seller_id,
        amount=Decimal(str(data.amount)),
        status="PENDING",
        auto_refund_at=_utcnow() + PENDING_ESCROW_TIMEOUT,
        idempotency_key=data.idempotency_key,
    )
    db.add(new_escrow)
    db.flush()
    record_transfer(db, buyer.id, "ESCROW:" + new_escrow.id, amount, "ESCROW_LOCK", new_escrow.id, from_node=buyer)
    db.commit()

    return {"escrow_id": new_escrow.id, "status": "FUNDS_LOCKED"}


@router.post("/v1/trade/escrow/settle", dependencies=[Depends(enforce_node_rate_limit)])
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


@router.post("/v1/tasks/create", dependencies=[Depends(enforce_node_rate_limit)])
def create_task(data: schemas.TaskCreate, buyer: models.Node = Depends(get_node), db: Session = Depends(get_db)) -> dict:
    """Create a task and auto-lock funds in escrow.

    Auth: API key.  Atomically deducts the skill price from the buyer's
    balance (row-locked), creates a PENDING escrow, and opens an OPEN task
    assigned to the skill's provider.
    """
    skill = db.query(models.Skill).filter(models.Skill.id == data.skill_id).first()
    if not skill: raise HTTPException(status_code=404, detail="Skill not found")

    # Sandbox isolation: sandbox buyers can use house skills and other sandbox skills,
    # but not skills from real third-party sellers (prevents fake TCK leaking to real economy)
    if buyer.is_sandbox and skill.provider_id not in ("botnode-official", "house"):
        seller_node = db.query(models.Node).filter(models.Node.id == skill.provider_id).first()
        if seller_node and not seller_node.is_sandbox:
            raise HTTPException(status_code=403, detail="Sandbox nodes cannot purchase from real sellers")

    # Canary mode: exposure caps
    if buyer.max_escrow_per_task and skill.price_tck > buyer.max_escrow_per_task:
        raise HTTPException(status_code=400, detail=f"Task price {skill.price_tck} exceeds your per-task cap of {buyer.max_escrow_per_task} TCK")
    if buyer.max_spend_daily:
        from sqlalchemy import func as sqlfunc
        today_start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        spent_today = db.query(sqlfunc.coalesce(sqlfunc.sum(models.Escrow.amount), 0)).filter(
            models.Escrow.buyer_id == buyer.id,
            models.Escrow.created_at >= today_start,
        ).scalar()
        if spent_today + skill.price_tck > buyer.max_spend_daily:
            raise HTTPException(status_code=400, detail=f"Daily spend cap reached ({spent_today}/{buyer.max_spend_daily} TCK)")

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
    db.flush()
    from webhook_service import dispatch_event
    dispatch_event(db, "task.created", {"task_id": new_task.id, "skill_id": data.skill_id}, node_id=skill.provider_id)
    db.commit()

    return {"task_id": new_task.id, "escrow_id": new_escrow.id, "status": "QUEUED"}


@router.get("/v1/tasks/mine")
def get_my_tasks(
    status: str = "OPEN",
    seller: models.Node = Depends(get_node),
    db: Session = Depends(get_db),
) -> dict:
    """List tasks assigned to the authenticated seller, filtered by status.

    Auth: API key.  Sellers poll this endpoint to discover work to do.
    Third-party seller agents use this in a loop: poll → execute → complete.
    The internal Task Runner also uses this for house skills.
    """
    tasks = db.query(models.Task).filter(
        models.Task.seller_id == seller.id,
        models.Task.status == status,
    ).order_by(models.Task.created_at.asc()).all()

    # Pre-fetch skill labels for all tasks
    skill_ids = list(set(t.skill_id for t in tasks if t.skill_id))
    skill_map = {}
    if skill_ids:
        skills = db.query(models.Skill).filter(models.Skill.id.in_(skill_ids)).all()
        skill_map = {s.id: s.label for s in skills}

    return {
        "node_id": seller.id,
        "status_filter": status,
        "tasks": [
            {
                "task_id": t.id,
                "skill_id": t.skill_id,
                "skill_label": skill_map.get(t.skill_id, t.skill_id),
                "buyer_id": t.buyer_id,
                "input_data": t.input_data,
                "escrow_id": t.escrow_id,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tasks
        ],
        "count": len(tasks),
    }


@router.post("/v1/tasks/{task_id}/claim")
def claim_task(task_id: str, seller: models.Node = Depends(get_node), db: Session = Depends(get_db)) -> dict:
    """Claim a task for execution by marking it IN_PROGRESS.

    Prevents duplicate execution when multiple task runners poll simultaneously.
    Only OPEN tasks assigned to the seller can be claimed.
    """
    task = db.query(models.Task).filter(models.Task.id == task_id).with_for_update().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.seller_id != seller.id:
        raise HTTPException(status_code=403, detail="Not your task")
    if task.status != "OPEN":
        raise HTTPException(status_code=409, detail="Task already claimed or completed")
    task.status = "IN_PROGRESS"
    db.commit()
    return {"status": "IN_PROGRESS", "task_id": task_id}


@router.post("/v1/tasks/complete")
def complete_task(data: schemas.TaskComplete, seller: models.Node = Depends(get_node), db: Session = Depends(get_db)) -> dict:
    """Mark a task as completed and open the 24-hour dispute window.

    DEBUG: log caller stack trace to find ghost completer.

    Auth: API key (seller only).  Transitions the task from OPEN to COMPLETED
    and the escrow from PENDING to AWAITING_SETTLEMENT with ``auto_settle_at``
    set 24 hours in the future.
    """
    task = db.query(models.Task).filter(models.Task.id == data.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.seller_id != seller.id:
        raise HTTPException(status_code=403, detail="Not your task")

    # FSM: only OPEN or IN_PROGRESS tasks can be completed
    if task.status not in ("OPEN", "IN_PROGRESS"):
        raise HTTPException(status_code=400, detail="Task cannot be completed from current state")

    # Update Task
    task.output_data = data.output_data
    task.status = "COMPLETED"

    # Schedule Settle Escrow — sandbox settles in 10s, production in 24h
    escrow = db.query(models.Escrow).filter(models.Escrow.id == task.escrow_id).first()
    escrow.status = "AWAITING_SETTLEMENT"
    buyer_node = db.query(models.Node).filter(models.Node.id == escrow.buyer_id).first()
    if buyer_node and buyer_node.is_sandbox:
        from datetime import timedelta
        escrow.auto_settle_at = _utcnow() + timedelta(seconds=60)
    else:
        escrow.auto_settle_at = _utcnow() + DISPUTE_WINDOW
    escrow.proof_hash = data.proof_hash

    from webhook_service import dispatch_event
    dispatch_event(db, "task.completed", {"task_id": task.id, "skill_id": task.skill_id}, node_id=task.buyer_id)
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

    # Store verification evidence if provided
    evidence_note = None
    if data.verification_evidence:
        evidence_note = f"Verification evidence attached: verifier={data.verification_evidence.get('verifier_skill', 'unknown')}, score={data.verification_evidence.get('score', 'N/A')}, verdict={data.verification_evidence.get('verdict', 'N/A')}"

    # Log the dispute with evidence
    dispute_log = models.DisputeRulesLog(
        task_id=task.id,
        escrow_id=escrow.id,
        rule_applied="BUYER_DISPUTE",
        rule_details={"reason": data.reason, "verification_evidence": data.verification_evidence},
        action_taken="FLAGGED_MANUAL",
    )
    db.add(dispute_log)
    db.commit()

    result = {"status": "DISPUTE_OPEN", "message": "Funds frozen. Manual node audit initiated."}
    if data.verification_evidence:
        result["evidence_attached"] = True
        result["evidence_summary"] = evidence_note
    return result


@router.post("/v1/nodes/me/canary")
def set_canary_caps(
    max_spend_daily: float = None,
    max_escrow_per_task: float = None,
    node: models.Node = Depends(get_node),
    db: Session = Depends(get_db),
) -> dict:
    """Set exposure caps on your own node (canary mode).

    Limits how much TCK the node can spend per day or per task.
    Set to ``null`` to remove a cap.  Enterprise-friendly blast radius control.
    """
    from decimal import Decimal
    if max_spend_daily is not None:
        node.max_spend_daily = Decimal(str(max_spend_daily)) if max_spend_daily > 0 else None
    if max_escrow_per_task is not None:
        node.max_escrow_per_task = Decimal(str(max_escrow_per_task)) if max_escrow_per_task > 0 else None
    db.commit()
    return {
        "node_id": node.id,
        "max_spend_daily": str(node.max_spend_daily) if node.max_spend_daily else None,
        "max_escrow_per_task": str(node.max_escrow_per_task) if node.max_escrow_per_task else None,
    }
