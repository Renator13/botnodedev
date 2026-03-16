"""Reputation and Genesis program endpoints."""

from decimal import Decimal
from datetime import timedelta

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

import models
import schemas
from dependencies import (
    limiter, audit_log, _utcnow, get_db, get_current_node,
)
from worker import recalculate_cri

router = APIRouter(tags=["reputation"])


@router.post("/v1/report/malfeasance")
@limiter.limit("3/hour")
def report_malfeasance(request: Request, node_id: str, reporter: models.Node = Depends(get_current_node), db: Session = Depends(get_db)) -> dict:
    """Report a node for malfeasance, applying a reputation strike.

    Auth: JWT or API key.  Rate limit: 3 per hour.
    Self-reporting is blocked.  Each strike reduces ``reputation_score`` by 10%.
    At 3 strikes the node is permanently banned, its balance confiscated, and
    CRI set to 0.  Genesis CRI-floor protection is honoured for < 3 strikes
    within the 180-day window.
    """
    if reporter.id == node_id:
        raise HTTPException(status_code=400, detail="Cannot report yourself")
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node: raise HTTPException(status_code=404, detail="Node not found")

    node.strikes += 1
    # Standard penalty
    node.reputation_score *= 0.9 # 10% hit

    # Genesis CRI Floor Check: If Node has badge, keep CRI >= 1.0 (for 180 days)
    # UNLESS strikes >= 3 (malfeasance overrides protection)
    if node.has_genesis_badge and node.first_settled_tx_at and node.strikes < 3:
        protection_period = timedelta(days=180)
        if _utcnow() <= (node.first_settled_tx_at + protection_period):
            if node.reputation_score < 1.0:
                node.reputation_score = 1.0

    if node.strikes >= 3:
        node.active = False
        confiscated = node.balance
        node.balance = Decimal("0")
        node.cri_score = 0.0
        node.cri_updated_at = _utcnow()
        db.commit()
        audit_log.warning(f"NODE_BANNED node={node_id} confiscated={confiscated} reporter={reporter.id}")
        return {
            "event": "PERMANENT_NODE_PURGE",
            "node_id": node_id,
            "confiscated_balance": confiscated,
            "status": "BANNED"
        }

    # Recalculate CRI after strike
    recalculate_cri(node, db)
    db.commit()
    audit_log.info(f"MALFEASANCE_STRIKE reporter={reporter.id} target={node_id} strikes={node.strikes}")
    return {"status": "STRIKE_LOGGED", "current_strikes": node.strikes}


@router.get("/v1/genesis", response_model=list[schemas.GenesisHallOfFameEntry])
def get_genesis_hall_of_fame(db: Session = Depends(get_db)) -> list:
    """Return the Genesis Hall of Fame (top 200 Genesis Nodes).

    Source of truth is GenesisBadgeAward, joined with Node for live
    reputation/activation data and EarlyAccessSignup for human-readable
    node_name when available.
    """
    # Explicit join to avoid N+1 lookups when resolving node + signup data
    query = (
        db.query(models.GenesisBadgeAward, models.Node, models.EarlyAccessSignup)
        .join(models.Node, models.GenesisBadgeAward.node_id == models.Node.id)
        .outerjoin(
            models.EarlyAccessSignup,
            models.EarlyAccessSignup.linked_node_id == models.Node.id,
        )
        .order_by(models.GenesisBadgeAward.genesis_rank.asc())
        .limit(200)
    )

    results = []
    for award, node, signup in query.all():
        results.append(
            schemas.GenesisHallOfFameEntry(
                rank=award.genesis_rank,
                node_id=node.id,
                name=getattr(signup, "node_name", None),
                awarded_at=award.awarded_at,
            )
        )

    return results
