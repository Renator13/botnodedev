"""Marketplace endpoints: browse and publish skill listings."""

import time
from decimal import Decimal
from statistics import median

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional

import models
import schemas
from dependencies import get_db, get_current_node
from config import LISTING_FEE
from ledger import record_transfer, VAULT

router = APIRouter(prefix="/v1/marketplace", tags=["marketplace"])


@router.get("")
def get_marketplace(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, max_length=200),
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    category: Optional[str] = Query(None, max_length=50),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """Browse the skill marketplace with optional search, price, and category filters.

    Auth: none (public).  Paginated via ``limit``/``offset`` (max 200 per page).
    Returns serialized skill listings with total count for client-side pagination.
    """
    query = db.query(models.Skill)

    if q:
        query = query.filter(models.Skill.label.ilike(f"%{q}%"))
    if min_price is not None:
        query = query.filter(models.Skill.price_tck >= min_price)
    if max_price is not None:
        query = query.filter(models.Skill.price_tck <= max_price)
    if category:
        query = query.filter(models.Skill.metadata_json.isnot(None))
        query = query.filter(models.Skill.metadata_json["category"].astext == category)

    total = query.count()
    skills = query.offset(offset).limit(limit).all()

    # Compute price stats across ALL active skills (unfiltered)
    stats_row = db.query(
        func.min(models.Skill.price_tck),
        func.max(models.Skill.price_tck),
        func.avg(models.Skill.price_tck),
    ).first()
    all_prices = [
        float(r[0])
        for r in db.query(models.Skill.price_tck)
        .filter(models.Skill.price_tck.isnot(None))
        .all()
    ]
    price_stats = None
    if all_prices:
        price_stats = {
            "min": str(stats_row[0]),
            "max": str(stats_row[1]),
            "average": str(round(stats_row[2], 2)),
            "median": str(round(median(all_prices), 2)),
        }

    return {
        "timestamp": int(time.time()),
        "market_status": "HIGH_LIQUIDITY",
        "total": total,
        "limit": limit,
        "offset": offset,
        "price_stats": price_stats,
        "listings": [
            _serialize_skill(s)
            for s in skills
        ]
    }


@router.post("/publish")
def publish_listing(data: schemas.PublishOffer, node: models.Node = Depends(get_current_node), db: Session = Depends(get_db)) -> dict:
    """Publish a new skill listing on the marketplace.

    Auth: JWT or API key.  Deducts a 0.50 TCK listing fee (row-locked to
    prevent double-spend).  The skill becomes immediately discoverable via
    ``GET /v1/marketplace``.
    """
    node = db.query(models.Node).filter(models.Node.id == node.id).with_for_update().first()
    if node.balance < LISTING_FEE:
        raise HTTPException(status_code=402, detail="Insufficient funds for publishing fee")

    new_skill = models.Skill(
        provider_id=node.id,
        label=data.label,
        price_tck=data.price_tck,
        metadata_json=data.metadata
    )
    db.add(new_skill)
    db.flush()
    record_transfer(db, node.id, VAULT, LISTING_FEE, "LISTING_FEE", new_skill.id, from_node=node)
    db.commit()

    return {"status": "PUBLISHED", "skill_id": new_skill.id, "fee_deducted": "0.50"}


def _serialize_skill(s: models.Skill) -> dict:
    """Serialize a skill for marketplace response, including validators and verifiers."""
    import json
    metadata = s.metadata_json or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}

    result = {
        "id": s.id,
        "provider_id": s.provider_id,
        "label": s.label,
        "price_tck": str(s.price_tck),
        "metadata": s.metadata_json,
    }

    # Surface validators so buyers know what checks are applied
    validators = metadata.get("validators", [])
    if validators:
        result["validators"] = [v.get("type", "unknown") + (":" + v.get("field", "") if v.get("field") else "") for v in validators]

    # Surface recommended verifiers
    recommended = metadata.get("recommended_verifiers", [])
    if recommended:
        result["recommended_verifiers"] = recommended

    return result
