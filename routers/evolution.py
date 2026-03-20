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

    Queries all active nodes, computes TCK spent for each, and returns
    the top N sorted by tck_spent descending.  Includes level info for
    each entry.
    """
    limit = min(limit, 100)
    nodes = db.query(models.Node).filter(models.Node.active.is_(True)).all()

    entries = []
    for node in nodes:
        info = _compute_node_level(node, db)
        entries.append({
            "node_id": node.id,
            "level_id": info["level"]["id"],
            "level_name": info["level"]["name"],
            "emoji": info["level"]["emoji"],
            "tck_spent": info["tck_spent"],
            "cri": info["cri"],
            "has_genesis_badge": node.has_genesis_badge,
        })

    entries.sort(key=lambda e: e["tck_spent"], reverse=True)
    page = entries[offset:offset + limit]

    return {
        "leaderboard": page,
        "total": len(entries),
        "limit": limit,
        "offset": offset,
    }
