"""Task receipt and audit artifact export.

Aggregates all data related to a task into a single exportable receipt:
ledger movements, escrow lifecycle, dispute engine decisions, webhook
deliveries, proof hashes, and human-readable summary.

Makes BotNode enterprise-friendly, debuggable, and auditable.
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

import models
from dependencies import get_db, get_node, _utcnow

router = APIRouter(tags=["receipts"])


@router.get("/v1/tasks/{task_id}/receipt")
def get_task_receipt(
    task_id: str,
    caller: models.Node = Depends(get_node),
    db: Session = Depends(get_db),
) -> dict:
    """Export a complete receipt for a task.

    Aggregates: task metadata, escrow lifecycle, ledger movements,
    dispute engine decisions, webhook deliveries, and proof hash
    into a single JSON document suitable for audit or debugging.

    Auth: API key.  Only the buyer or seller of the task can access.
    """
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if caller.id not in (task.buyer_id, task.seller_id):
        raise HTTPException(status_code=403, detail="Not a party to this task")

    # Escrow
    escrow = None
    escrow_data = None
    if task.escrow_id:
        escrow = db.query(models.Escrow).filter(models.Escrow.id == task.escrow_id).first()
    if escrow:
        escrow_data = {
            "escrow_id": escrow.id,
            "status": escrow.status,
            "amount": str(escrow.amount),
            "dispute_reason": escrow.dispute_reason,
            "created_at": escrow.created_at.isoformat() if escrow.created_at else None,
            "auto_settle_at": escrow.auto_settle_at.isoformat() if escrow.auto_settle_at else None,
            "auto_refund_at": escrow.auto_refund_at.isoformat() if escrow.auto_refund_at else None,
        }

    # Ledger movements for this escrow
    ledger_entries = []
    if task.escrow_id:
        escrow_account = f"ESCROW:{task.escrow_id}"
        entries = (
            db.query(models.LedgerEntry)
            .filter(
                (models.LedgerEntry.account_id == escrow_account) |
                (models.LedgerEntry.counterparty_id == escrow_account) |
                (models.LedgerEntry.reference_id == task.escrow_id)
            )
            .order_by(models.LedgerEntry.created_at.asc())
            .all()
        )
        for e in entries:
            ledger_entries.append({
                "type": e.entry_type,
                "account": e.account_id,
                "counterparty": e.counterparty_id,
                "amount": str(e.amount),
                "balance_after": str(e.balance_after) if e.balance_after is not None else None,
                "reference_type": e.reference_type,
                "note": e.note,
                "timestamp": e.created_at.isoformat() if e.created_at else None,
            })

    # Dispute engine decisions
    disputes = (
        db.query(models.DisputeRulesLog)
        .filter(models.DisputeRulesLog.task_id == task_id)
        .order_by(models.DisputeRulesLog.created_at.asc())
        .all()
    )
    dispute_data = [
        {
            "rule": d.rule_applied,
            "action": d.action_taken,
            "details": d.rule_details,
            "timestamp": d.created_at.isoformat() if d.created_at else None,
        }
        for d in disputes
    ]

    # Webhook deliveries related to this task
    webhook_data = []
    deliveries = (
        db.query(models.WebhookDelivery)
        .filter(models.WebhookDelivery.payload.cast(models.String).contains(task_id))
        .order_by(models.WebhookDelivery.created_at.asc())
        .limit(20)
        .all()
    )
    for w in deliveries:
        webhook_data.append({
            "event": w.event_type,
            "status": w.status,
            "attempts": w.attempts,
            "last_response_code": w.last_response_code,
            "timestamp": w.created_at.isoformat() if w.created_at else None,
        })

    # Skill info
    skill = db.query(models.Skill).filter(models.Skill.id == task.skill_id).first()

    return {
        "receipt_id": f"rcpt_{task_id}",
        "generated_at": _utcnow().isoformat() + "Z",
        "task": {
            "task_id": task.id,
            "skill_id": task.skill_id,
            "skill_label": skill.label if skill else None,
            "buyer_id": task.buyer_id,
            "seller_id": task.seller_id,
            "status": task.status,
            "protocol": task.protocol,
            "llm_provider": task.llm_provider_used,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "has_output": task.output_data is not None,
        },
        "escrow": escrow_data,
        "ledger_movements": ledger_entries,
        "dispute_engine": dispute_data,
        "webhooks": webhook_data,
        "summary": _build_summary(task, escrow, ledger_entries, dispute_data),
    }


def _build_summary(task, escrow, ledger, disputes) -> str:
    """Generate a human-readable one-line summary of the task lifecycle."""
    parts = [f"Task {task.id[:8]}"]
    if escrow:
        parts.append(f"escrow {escrow.status} ({escrow.amount} TCK)")
    if disputes:
        parts.append(f"{len(disputes)} dispute rule(s) fired")
    parts.append(f"{len(ledger)} ledger entries")
    return " · ".join(parts)
