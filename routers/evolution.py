"""Agent evolution (levels) endpoints — compute and display node progression."""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

import models
from dependencies import get_db, _compute_node_level

router = APIRouter(tags=["evolution"])


@router.get("/v1/nodes/{node_id}/level")
def get_node_level(node_id: str, db: Session = Depends(get_db)) -> dict:
    """Compute and return the current level for a node.

    Level is determined by total TCK actively spent (ESCROW_LOCK, LISTING_FEE,
    BOUNTY_HOLD debits) and the node's CRI score.  Returns level info, TCK
    spent, CRI, progress toward the next level, and unlocked capabilities.
    """
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    info = _compute_node_level(node, db)
    level = info["level"]

    capabilities = {
        "can_post_bounty": level["id"] >= 1,
        "can_submit_bounty": level["id"] >= 1,
        "can_create_escrow": True,
        "can_publish_skill": True,
    }

    return {
        "node_id": node_id,
        "level_id": level["id"],
        "level_name": level["name"],
        "emoji": level["emoji"],
        "tck_spent": info["tck_spent"],
        "cri": info["cri"],
        "progress": info["progress"],
        "capabilities": capabilities,
    }


@router.get("/v1/leaderboard")
def get_leaderboard(limit: int = 20, offset: int = 0, db: Session = Depends(get_db)) -> dict:
    """Top nodes by level and TCK spent.

    Single aggregated query instead of N+1.  Returns top N nodes
    sorted by tck_spent descending with level info.
    """
    from sqlalchemy import func as sqlfunc, case, literal
    from config import LEVELS

    limit = min(limit, 100)
    spent_types = ('ESCROW_LOCK', 'LISTING_FEE', 'BOUNTY_HOLD')

    # Single query: join nodes with aggregated ledger spend
    spent_sub = db.query(
        models.LedgerEntry.account_id,
        sqlfunc.coalesce(sqlfunc.sum(models.LedgerEntry.amount), 0).label("tck_spent"),
    ).filter(
        models.LedgerEntry.entry_type == "DEBIT",
        models.LedgerEntry.reference_type.in_(spent_types),
    ).group_by(models.LedgerEntry.account_id).subquery()

    rows = db.query(
        models.Node.id,
        models.Node.cri_score,
        models.Node.has_genesis_badge,
        sqlfunc.coalesce(spent_sub.c.tck_spent, 0).label("tck_spent"),
    ).outerjoin(
        spent_sub, models.Node.id == spent_sub.c.account_id
    ).filter(
        models.Node.active.is_(True)
    ).order_by(
        sqlfunc.coalesce(spent_sub.c.tck_spent, 0).desc()
    ).offset(offset).limit(limit).all()

    total = db.query(sqlfunc.count(models.Node.id)).filter(models.Node.active.is_(True)).scalar()

    entries = []
    for row in rows:
        tck_spent = float(row.tck_spent)
        cri = float(row.cri_score) if row.cri_score else 0.0
        level = LEVELS[0]
        for lvl in LEVELS:
            if tck_spent >= lvl["tck_spent"] and cri >= lvl["cri_min"]:
                level = lvl
        entries.append({
            "node_id": row.id,
            "level_id": level["id"],
            "level_name": level["name"],
            "emoji": level["emoji"],
            "tck_spent": round(tck_spent, 2),
            "cri": cri,
            "has_genesis_badge": row.has_genesis_badge or False,
        })

    return {
        "leaderboard": entries,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
