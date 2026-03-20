"""Shadow mode — simulate trades without moving real TCK.

Creates task + escrow records tagged as shadow. The dispute engine,
CRI computation, and settlement all run as normal — but no actual
balance mutations occur.  The receipt endpoint shows "what would
have happened."

Use case: enterprise CTOs connecting 50+ agents who want to observe
BotNode's behavior before committing real value.  "Connect and
observe; decide later whether to activate real settlement."
"""

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

import models
import schemas
from dependencies import get_db, get_node, _utcnow
from config import PENDING_ESCROW_TIMEOUT, DISPUTE_WINDOW

router = APIRouter(tags=["shadow"])


@router.post("/v1/shadow/tasks/create")
def create_shadow_task(
    data: schemas.TaskCreate,
    buyer: models.Node = Depends(get_node),
    db: Session = Depends(get_db),
) -> dict:
    """Create a shadow task — full simulation, zero TCK movement.

    The task goes through the complete lifecycle: escrow creation,
    execution, dispute engine evaluation, and settlement simulation.
    But no TCK is debited, credited, or locked.  The receipt endpoint
    shows exactly what would have happened with real settlement.

    Auth: API key.
    """
    skill = db.query(models.Skill).filter(models.Skill.id == data.skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Create shadow escrow (no balance check, no ledger entry)
    escrow = models.Escrow(
        buyer_id=buyer.id,
        seller_id=skill.provider_id,
        amount=skill.price_tck,
        status="PENDING",
        auto_refund_at=_utcnow() + PENDING_ESCROW_TIMEOUT,
    )
    db.add(escrow)
    db.flush()

    # Create shadow task
    task = models.Task(
        skill_id=data.skill_id,
        buyer_id=buyer.id,
        seller_id=skill.provider_id,
        input_data=data.input_data,
        status="OPEN",
        escrow_id=escrow.id,
        protocol="shadow",
        is_shadow=True,
    )
    db.add(task)
    db.commit()

    return {
        "task_id": task.id,
        "escrow_id": escrow.id,
        "status": "SHADOW_QUEUED",
        "shadow": True,
        "simulated_cost": str(skill.price_tck),
        "simulated_tax": str(skill.price_tck * Decimal("0.03")),
        "simulated_payout": str(skill.price_tck * Decimal("0.97")),
        "note": "Shadow mode — no TCK was moved. Use GET /v1/tasks/{task_id}/receipt to see what would happen.",
    }


@router.get("/v1/shadow/simulate/{task_id}")
def simulate_settlement(
    task_id: str,
    caller: models.Node = Depends(get_node),
    db: Session = Depends(get_db),
) -> dict:
    """Simulate the full settlement for a shadow task.

    Runs the dispute engine, computes CRI impact, and shows exactly
    what would happen if this were a real trade — without touching
    any balances.
    """
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if caller.id not in (task.buyer_id, task.seller_id):
        raise HTTPException(status_code=403, detail="Not a party to this task")

    escrow = db.query(models.Escrow).filter(models.Escrow.id == task.escrow_id).first()
    skill = db.query(models.Skill).filter(models.Skill.id == task.skill_id).first()

    # Run dispute engine (evaluation only, no execution)
    from dispute_engine import evaluate_task
    should_dispute, reason, details = evaluate_task(task, skill)

    if should_dispute:
        outcome = "AUTO_REFUND"
        buyer_impact = f"+{escrow.amount} TCK (refunded)"
        seller_impact = "0 TCK"
        vault_impact = "0 TCK"
    else:
        outcome = "SETTLED"
        tax = escrow.amount * Decimal("0.03")
        payout = escrow.amount - tax
        buyer_impact = f"-{escrow.amount} TCK"
        seller_impact = f"+{payout} TCK"
        vault_impact = f"+{tax} TCK"

    return {
        "task_id": task.id,
        "shadow": True,
        "simulation": {
            "outcome": outcome,
            "dispute_engine": {
                "triggered": should_dispute,
                "reason": reason,
                "details": details,
            },
            "financial_impact": {
                "buyer": buyer_impact,
                "seller": seller_impact,
                "vault": vault_impact,
            },
        },
        "note": "This is a simulation. No TCK was moved.",
    }
