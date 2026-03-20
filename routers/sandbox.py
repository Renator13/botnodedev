"""Sandbox mode for risk-free developer onboarding.

Creates ephemeral nodes with 10,000 fake $TCK that auto-settle in
10 seconds instead of 24 hours.  Sandbox nodes auto-expire after 7
days and are excluded from Genesis, leaderboards, and real metrics.

This removes all friction from the quickstart: a developer can
register, publish, buy, and settle — all in under 60 seconds.
"""

import secrets
from decimal import Decimal

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from dependencies import get_db, _utcnow, pwd_context, limiter
from ledger import record_transfer, MINT
from config import INITIAL_NODE_BALANCE

router = APIRouter(tags=["sandbox"])

SANDBOX_BALANCE = Decimal("10000.00")
"""TCK credited to sandbox nodes (100x the normal grant)."""


class SandboxRequest(BaseModel):
    alias: str = Field("sandbox-agent", max_length=100)


@router.post("/v1/sandbox/nodes")
@limiter.limit("20/hour")
def create_sandbox_node(request: Request, req: SandboxRequest, db: Session = Depends(get_db)) -> dict:
    """Create a sandbox node with 10,000 fake $TCK.

    Sandbox nodes:
    - Get 10,000 TCK (not 100)
    - Escrow auto-settles in 10 seconds (not 24 hours)
    - Excluded from Genesis, leaderboards, and real metrics
    - Auto-expire after 7 days
    - node_id starts with ``sandbox_``

    No challenge required — instant creation.
    """
    # Use hex-only node_id (no underscores) so bn_{node_id}_{secret} parsing works
    node_id = f"sandbox-{secrets.token_hex(8)}"
    raw_secret = secrets.token_hex(24)
    api_key = f"bn_{node_id}_{raw_secret}"
    api_key_hash = pwd_context.hash(raw_secret)

    node = models.Node(
        id=node_id,
        api_key_hash=api_key_hash,
        balance=Decimal("0"),
        cri_score=50.0,
        is_sandbox=True,
    )
    db.add(node)
    db.flush()

    # MINT sandbox TCK
    record_transfer(
        db, MINT, node_id, SANDBOX_BALANCE,
        "REGISTRATION_CREDIT", node_id,
        to_node=node, note="sandbox_init",
    )

    db.commit()

    return {
        "node_id": node_id,
        "api_key": api_key,
        "balance": str(SANDBOX_BALANCE),
        "cri_score": 50.0,
        "sandbox": True,
        "expires_in": "7 days",
        "note": "Sandbox node — trades settle in 10 seconds, not 24 hours.",
    }
