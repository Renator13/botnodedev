"""Marketplace endpoints: browse and publish skill listings."""

import time
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

import models
import schemas
from dependencies import get_db, get_current_node

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

    return {
        "timestamp": int(time.time()),
        "market_status": "HIGH_LIQUIDITY",
        "total": total,
        "limit": limit,
        "offset": offset,
        "listings": [
            {"id": s.id, "provider_id": s.provider_id, "label": s.label, "price_tck": str(s.price_tck), "metadata": s.metadata_json}
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
    if node.balance < Decimal("0.5"):
        raise HTTPException(status_code=402, detail="Insufficient funds for publishing fee")
    node.balance -= Decimal("0.5")

    new_skill = models.Skill(
        provider_id=node.id,
        label=data.label,
        price_tck=data.price_tck,
        metadata_json=data.metadata
    )
    db.add(new_skill)
    db.commit()

    return {"status": "PUBLISHED", "skill_id": new_skill.id, "fee_deducted": "0.50"}
