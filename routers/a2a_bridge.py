"""A2A (Agent-to-Agent) Protocol bridge for BotNode.

Implements Google's A2A protocol as a second entry point to the BotNode
marketplace, alongside the existing MCP bridge.  This makes BotNode
protocol-neutral: MCP agents, A2A agents, and direct API users all
trade on the same marketplace with the same escrow and CRI.

Endpoints:
    GET  /.well-known/agent.json       — A2A Agent Card (discovery)
    POST /v1/a2a/tasks/send            — Create task via A2A
    GET  /v1/a2a/tasks/{task_id}       — Query task status (A2A lifecycle)
    GET  /v1/a2a/discover              — Browse skills in A2A format
"""

import json
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from dependencies import get_db, get_node, _utcnow, _compute_node_level, enforce_node_rate_limit
from config import PROTOCOL_TAX_RATE, PENDING_ESCROW_TIMEOUT
from ledger import record_transfer

router = APIRouter(tags=["a2a"])


# ---------------------------------------------------------------------------
# Agent Card (A2A discovery)
# ---------------------------------------------------------------------------

@router.get("/.well-known/agent.json")
def agent_card(db: Session = Depends(get_db)) -> dict:
    """A2A Agent Card — standard discovery endpoint.

    Any A2A-compatible agent can discover BotNode's capabilities
    by fetching this URL.  Returns the full skill catalog with
    input/output schemas and pricing.
    """
    skills = db.query(models.Skill).limit(200).all()

    return {
        "name": "BotNode Grid",
        "description": (
            "Agent-to-agent marketplace with escrow-backed settlement, "
            "portable CRI reputation, and multi-protocol support."
        ),
        "url": "https://botnode.io",
        "version": "1.0.0",
        "protocol": "a2a",
        "capabilities": {
            "streaming": False,
            "pushNotifications": True,
            "stateTransitionHistory": True,
        },
        "authentication": {
            "schemes": ["apiKey"],
            "apiKey": {"headerName": "X-API-KEY"},
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": s.id,
                "name": s.label,
                "price_tck": str(s.price_tck),
                "inputSchema": _extract_schema(s.metadata_json, "input_schema"),
                "outputSchema": _extract_schema(s.metadata_json, "output_schema"),
            }
            for s in skills
        ],
    }


# ---------------------------------------------------------------------------
# Create task via A2A
# ---------------------------------------------------------------------------

class A2ATaskSend(BaseModel):
    """A2A task creation request."""
    skill_id: str = Field(..., max_length=100)
    input: dict
    callback_url: Optional[str] = Field(None, max_length=500)


@router.post("/v1/a2a/tasks/send", dependencies=[Depends(enforce_node_rate_limit)])
def a2a_send_task(
    req: A2ATaskSend,
    buyer: models.Node = Depends(get_node),
    db: Session = Depends(get_db),
) -> dict:
    """Create a task via A2A protocol with escrow-backed settlement.

    Translates the A2A request into BotNode's internal flow:
    A2A task → escrow lock → skill execution → settlement.
    The task is tagged with ``protocol='a2a'`` for trade graph tracking.
    """
    skill = db.query(models.Skill).filter(models.Skill.id == req.skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Sandbox isolation
    if buyer.is_sandbox and skill.provider_id not in ("botnode-official", "house"):
        seller_node = db.query(models.Node).filter(models.Node.id == skill.provider_id).first()
        if seller_node and not seller_node.is_sandbox:
            raise HTTPException(status_code=403, detail="Sandbox nodes cannot purchase from real sellers")

    # Lock buyer row
    buyer = db.query(models.Node).filter(models.Node.id == buyer.id).with_for_update().first()
    if buyer.balance < skill.price_tck:
        raise HTTPException(status_code=402, detail="Insufficient TCK balance")

    # Create escrow
    escrow = models.Escrow(
        buyer_id=buyer.id,
        seller_id=skill.provider_id,
        amount=skill.price_tck,
        status="PENDING",
        auto_refund_at=_utcnow() + PENDING_ESCROW_TIMEOUT,
    )
    db.add(escrow)
    db.flush()
    record_transfer(db, buyer.id, "ESCROW:" + escrow.id, Decimal(str(skill.price_tck)),
                    "ESCROW_LOCK", escrow.id, from_node=buyer)

    # Create task with protocol tag
    task = models.Task(
        skill_id=req.skill_id,
        buyer_id=buyer.id,
        seller_id=skill.provider_id,
        input_data=req.input,
        status="OPEN",
        escrow_id=escrow.id,
        protocol="a2a",
        integration="a2a",
        capability=req.callback_url,  # store callback URL in capability field
    )
    db.add(task)
    db.flush()

    # Dispatch webhook if seller has one
    from webhook_service import dispatch_event
    dispatch_event(db, "task.created", {"task_id": task.id, "skill_id": req.skill_id, "protocol": "a2a"},
                   node_id=skill.provider_id)

    db.commit()

    return {
        "task_id": task.id,
        "status": "submitted",
        "escrow_id": escrow.id,
        "price_tck": str(skill.price_tck),
        "protocol": "a2a",
    }


# ---------------------------------------------------------------------------
# Query task status (A2A lifecycle)
# ---------------------------------------------------------------------------

_STATUS_MAP = {
    "OPEN": "submitted",
    "COMPLETED": "completed",
    "DISPUTED": "input-required",
    "SETTLED": "completed",
    "REFUNDED": "canceled",
}


@router.get("/v1/a2a/tasks/{task_id}")
def a2a_get_task(
    task_id: str,
    caller: models.Node = Depends(get_node),
    db: Session = Depends(get_db),
) -> dict:
    """Query A2A task status with lifecycle mapping.

    Maps BotNode internal states to A2A standard lifecycle:
    OPEN→submitted, COMPLETED→completed, DISPUTED→input-required.
    """
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if caller.id not in (task.buyer_id, task.seller_id):
        raise HTTPException(status_code=403, detail="Not a party to this task")

    result = {
        "task_id": task.id,
        "status": _STATUS_MAP.get(task.status, "unknown"),
        "botnode_status": task.status,
        "escrow_id": task.escrow_id,
        "protocol": task.protocol or "a2a",
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }

    if task.output_data:
        result["output"] = task.output_data

    # Include seller CRI for trust signal
    if task.seller_id:
        seller = db.query(models.Node).filter(models.Node.id == task.seller_id).first()
        if seller:
            result["seller_cri"] = round(seller.cri_score or 30.0, 1)

    return result


# ---------------------------------------------------------------------------
# Discover skills (A2A format)
# ---------------------------------------------------------------------------

@router.get("/v1/a2a/discover")
def a2a_discover(
    category: Optional[str] = None,
    max_price_tck: Optional[float] = None,
    min_seller_cri: Optional[float] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> dict:
    """Browse BotNode skills in A2A format with optional filters.

    No auth required — skill discovery is public.
    """
    query = db.query(models.Skill)
    if limit > 200:
        limit = 200

    skills = query.limit(limit).all()

    result = []
    for s in skills:
        seller = db.query(models.Node).filter(models.Node.id == s.provider_id).first()
        seller_cri = round(seller.cri_score or 30.0, 1) if seller else 0

        if max_price_tck and float(s.price_tck) > max_price_tck:
            continue
        if min_seller_cri and seller_cri < min_seller_cri:
            continue

        metadata = s.metadata_json or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}

        result.append({
            "id": s.id,
            "name": s.label,
            "price_tck": str(s.price_tck),
            "seller_cri": seller_cri,
            "category": metadata.get("category", "general"),
            "description": metadata.get("description", ""),
            "inputSchema": _extract_schema(s.metadata_json, "input_schema"),
            "outputSchema": _extract_schema(s.metadata_json, "output_schema"),
        })

    return {"skills": result, "total": len(result), "protocol": "a2a"}


# ---------------------------------------------------------------------------
# Network stats (Feature 4: Trade Graph)
# ---------------------------------------------------------------------------

@router.get("/v1/network/stats")
def network_stats(db: Session = Depends(get_db)) -> dict:
    """Cross-protocol trade graph statistics.

    Public endpoint — shows network activity by protocol, LLM provider,
    and trade volume.  This is the data that demonstrates BotNode's
    protocol-neutral position and creates the moat.
    """
    from sqlalchemy import func, distinct, case
    now = _utcnow()

    # By protocol
    proto_rows = (
        db.query(models.Task.protocol, func.count(models.Task.id))
        .filter(models.Task.status.in_(["COMPLETED", "OPEN"]))
        .group_by(models.Task.protocol)
        .all()
    )
    by_protocol = {(r[0] or "api"): r[1] for r in proto_rows}

    # By LLM provider
    prov_rows = (
        db.query(models.Task.llm_provider_used, func.count(models.Task.id))
        .filter(models.Task.llm_provider_used.isnot(None))
        .group_by(models.Task.llm_provider_used)
        .all()
    )
    by_provider = {r[0]: r[1] for r in prov_rows}

    total_trades = sum(by_protocol.values())
    total_nodes = db.query(func.count(models.Node.id)).scalar() or 0
    total_skills = db.query(func.count(models.Skill.id)).scalar() or 0

    return {
        "overview": {
            "total_trades": total_trades,
            "total_nodes": total_nodes,
            "total_skills": total_skills,
            "protocols_active": [p for p in by_protocol if by_protocol[p] > 0],
            "llm_providers_active": list(by_provider.keys()),
        },
        "by_protocol": by_protocol,
        "by_provider": by_provider,
        "generated_at": now.isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_schema(metadata_json, key: str) -> dict:
    """Extract input/output schema from skill metadata."""
    if not metadata_json:
        return {"type": "object"}
    meta = metadata_json
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            return {"type": "object"}
    return meta.get(key, {"type": "object"})
