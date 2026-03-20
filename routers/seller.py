"""Seller dashboard endpoints — aggregated stats for skill providers."""

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc

import models
from dependencies import get_db, get_current_node, _compute_node_level

router = APIRouter(tags=["seller"])


@router.get("/v1/seller/stats")
def seller_stats(
    node: models.Node = Depends(get_current_node),
    db: Session = Depends(get_db),
) -> dict:
    """Return aggregated seller dashboard stats for the authenticated node.

    Auth: JWT or API key.

    Returns:
    - skills_published: list of skills with id, label, price, and times_hired
    - total_tck_earned: lifetime TCK earned from settled tasks + bounties
    - dispute_rate: fraction of seller tasks that were disputed
    - cri: current CRI score with factor breakdown
    - evolution: current level and progress
    """

    # ── Skills published by this node ────────────────────────────────
    skills = db.query(models.Skill).filter(
        models.Skill.provider_id == node.id,
    ).all()

    skills_published = []
    for skill in skills:
        times_hired = db.query(sqlfunc.count(models.Task.id)).filter(
            models.Task.skill_id == skill.id,
        ).scalar()
        skills_published.append({
            "id": skill.id,
            "label": skill.label,
            "price_tck": str(skill.price_tck),
            "times_hired": times_hired,
        })

    # ── Total TCK earned (CREDIT entries for settlement + bounty payouts) ─
    earned_types = ("ESCROW_SETTLE", "BOUNTY_RELEASE")
    total_earned_raw = db.query(
        sqlfunc.coalesce(sqlfunc.sum(models.LedgerEntry.amount), 0)
    ).filter(
        models.LedgerEntry.account_id == node.id,
        models.LedgerEntry.entry_type == "CREDIT",
        models.LedgerEntry.reference_type.in_(earned_types),
    ).scalar()
    total_tck_earned = str(Decimal(str(total_earned_raw)).quantize(Decimal("0.01")))

    # ── Dispute rate as seller ────────────────────────────────────────
    total_seller_tasks = db.query(sqlfunc.count(models.Task.id)).filter(
        models.Task.seller_id == node.id,
    ).scalar()

    disputed_escrows = 0
    if total_seller_tasks > 0:
        disputed_escrows = db.query(sqlfunc.count(models.Escrow.id)).filter(
            models.Escrow.seller_id == node.id,
            models.Escrow.status == "DISPUTED",
        ).scalar()

    dispute_rate = round(disputed_escrows / total_seller_tasks, 4) if total_seller_tasks > 0 else 0.0

    # ── CRI score + breakdown ────────────────────────────────────────
    cri_score = float(node.cri_score) if node.cri_score is not None else 0.0

    # Compute basic CRI factor breakdown from available data
    settled_as_seller = db.query(sqlfunc.count(models.Escrow.id)).filter(
        models.Escrow.seller_id == node.id,
        models.Escrow.status == "SETTLED",
    ).scalar()

    unique_counterparties = db.query(
        sqlfunc.count(sqlfunc.distinct(models.Escrow.buyer_id))
    ).filter(
        models.Escrow.seller_id == node.id,
        models.Escrow.status == "SETTLED",
    ).scalar()

    cri_breakdown = {
        "score": cri_score,
        "settled_transactions": settled_as_seller,
        "unique_counterparties": unique_counterparties,
        "disputes": disputed_escrows,
        "strikes": node.strikes or 0,
        "has_genesis_badge": node.has_genesis_badge or False,
    }

    # ── Evolution level ──────────────────────────────────────────────
    level_info = _compute_node_level(node, db)

    evolution = {
        "level_id": level_info["level"]["id"],
        "level_name": level_info["level"]["name"],
        "emoji": level_info["level"]["emoji"],
        "tck_spent": level_info["tck_spent"],
        "progress": level_info["progress"],
    }

    return {
        "node_id": node.id,
        "skills_published": skills_published,
        "total_tck_earned": total_tck_earned,
        "dispute_rate": dispute_rate,
        "cri": cri_breakdown,
        "evolution": evolution,
    }
