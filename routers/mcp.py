"""MCP (Model Context Protocol) bridge endpoints."""

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import models
import schemas
from dependencies import get_db, get_current_node, MCP_CAPABILITIES, _utcnow
from config import PENDING_ESCROW_TIMEOUT
from ledger import record_transfer

router = APIRouter(prefix="/v1/mcp", tags=["mcp"])


@router.post("/hire")
def mcp_hire(request_body: schemas.MCPHireRequest, buyer: models.Node = Depends(get_current_node), db: Session = Depends(get_db)) -> dict:
    """Hire an agent via MCP.

    This wraps the standard Task/Escrow flow but tags the task with
    integration + capability and enforces a max_price in TCK.
    """
    capability_cfg = MCP_CAPABILITIES.get(request_body.capability)
    if not capability_cfg:
        return JSONResponse(
            status_code=400,
            content={
                "error_type": "INVALID_CAPABILITY",
                "message": f"Unknown capability '{request_body.capability}'",
                "retry_hint": "change_capability",
            },
        )

    # Resolve price and skill
    typical_price = Decimal(str(capability_cfg.get("typical_price", 0)))
    max_price = Decimal(str(request_body.max_price or 0))

    if max_price <= 0 or typical_price > max_price:
        return JSONResponse(
            status_code=400,
            content={
                "error_type": "BAD_PAYLOAD",
                "message": "max_price too low for selected capability",
                "retry_hint": "lower_capability_cost",
            },
        )

    # For v1: look up a Skill that matches this capability, or fall back to a fixed ID
    skill_id = capability_cfg.get("skill_id")
    skill = None
    if skill_id:
        skill = db.query(models.Skill).filter(models.Skill.id == skill_id).first()
    if not skill:
        # Fallback: first skill whose label contains the capability name (very MVP)
        skill = db.query(models.Skill).filter(models.Skill.label.ilike(f"%{request_body.capability}%")).first()

    if not skill:
        return JSONResponse(
            status_code=400,
            content={
                "error_type": "GRID_ERROR",
                "message": "No matching skill found for capability",
                "retry_hint": "retry_later",
            },
        )

    price_tck = skill.price_tck

    # Sandbox isolation: prevent cross-realm trades via MCP bridge
    seller_node = db.query(models.Node).filter(models.Node.id == skill.provider_id).first()
    if buyer.is_sandbox and seller_node and not seller_node.is_sandbox and skill.provider_id not in ("botnode-official", "house"):
        return JSONResponse(
            status_code=403,
            content={"error_type": "SANDBOX_ISOLATION", "message": "Sandbox nodes cannot trade with production nodes via MCP", "retry_hint": "use_sandbox_skills"},
        )
    if not buyer.is_sandbox and seller_node and seller_node.is_sandbox:
        return JSONResponse(
            status_code=403,
            content={"error_type": "SANDBOX_ISOLATION", "message": "Production nodes cannot trade with sandbox nodes via MCP", "retry_hint": "use_production_skills"},
        )

    # Lock buyer row to prevent double-spend
    buyer = db.query(models.Node).filter(models.Node.id == buyer.id).with_for_update().first()
    if buyer.balance < price_tck:
        return JSONResponse(
            status_code=402,
            content={
                "error_type": "INSUFFICIENT_FUNDS",
                "message": "Balance insufficient for this capability",
                "retry_hint": "lower_max_price",
            },
        )
    new_escrow = models.Escrow(
        buyer_id=buyer.id,
        seller_id=skill.provider_id,
        amount=price_tck,
        status="PENDING",
        auto_refund_at=_utcnow() + PENDING_ESCROW_TIMEOUT,
    )
    db.add(new_escrow)
    db.flush()
    record_transfer(db, buyer.id, "ESCROW:" + new_escrow.id, price_tck, "ESCROW_LOCK", new_escrow.id, from_node=buyer)

    # Create task tagged as MCP
    new_task = models.Task(
        skill_id=skill.id,
        buyer_id=buyer.id,
        seller_id=skill.provider_id,
        input_data=request_body.payload,
        status="OPEN",
        escrow_id=new_escrow.id,
        integration=f"MCP_{request_body.integration.upper()}",
        capability=request_body.capability,
    )
    db.add(new_task)
    db.commit()

    return {
        "status": "QUEUED",
        "task_id": new_task.id,
        "escrow_id": new_escrow.id,
        "estimated_cost": str(price_tck),
        "eta_seconds": capability_cfg.get("eta_seconds", 30),
    }


@router.get("/tasks/{task_id}")
def mcp_get_task(task_id: str, caller: models.Node = Depends(get_current_node), db: Session = Depends(get_db)) -> dict:
    """Poll the status of a task created via MCP hire.

    Auth: JWT or API key.  Only the buyer or seller of the task may access it.
    Returns an MCP-compatible status (QUEUED/RUNNING/COMPLETED/FAILED) plus
    cost and output data when available.
    """
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        return JSONResponse(
            status_code=404,
            content={
                "error_type": "TASK_NOT_FOUND",
                "message": "Task not found",
                "retry_hint": "contact_human",
            },
        )

    # Only buyer or seller can view task details
    if caller.id not in (task.buyer_id, task.seller_id):
        raise HTTPException(status_code=403, detail="Not a party to this task")

    # Determine MCP-style status
    if task.status in ["OPEN", "IN_PROGRESS"]:
        status = "RUNNING"
    elif task.status == "COMPLETED":
        status = "COMPLETED"
    elif task.status in ["FAILED", "DISPUTED"]:
        status = "FAILED"
    else:
        status = "QUEUED"

    escrow = None
    cost = None
    if task.escrow_id:
        escrow = db.query(models.Escrow).filter(models.Escrow.id == task.escrow_id).first()
        if escrow and escrow.status in ["AWAITING_SETTLEMENT", "SETTLED"]:
            cost = str(escrow.amount)

    return {
        "status": status,
        "task_id": task.id,
        "escrow_id": task.escrow_id,
        "cost": cost,
        "output": task.output_data if status == "COMPLETED" else None,
        "error_type": None if status != "FAILED" else "GRID_ERROR",
        "error_message": None if status != "FAILED" else "Task failed or disputed",
        "retry_hint": None,
    }


@router.get("/wallet")
def mcp_wallet(node: models.Node = Depends(get_current_node), db: Session = Depends(get_db)) -> dict:
    """Return the caller's wallet summary: balance, pending escrows, and open tasks.

    Auth: JWT or API key.
    """
    pending_escrows = db.query(models.Escrow).filter(
        models.Escrow.buyer_id == node.id,
        models.Escrow.status.in_(["PENDING", "AWAITING_SETTLEMENT"]),
    ).count()

    open_tasks = db.query(models.Task).filter(
        models.Task.buyer_id == node.id,
        models.Task.status.in_(["OPEN", "IN_PROGRESS"]),
    ).count()

    return {
        "node_id": node.id,
        "balance_tck": str(node.balance),
        "pending_escrows": pending_escrows,
        "open_tasks": open_tasks,
    }
