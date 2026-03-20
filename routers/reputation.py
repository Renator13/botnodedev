"""Reputation, CRI explainability, portable certificates, and Genesis program endpoints."""

import math
import time
import os
from decimal import Decimal
from datetime import timedelta

import jwt as pyjwt
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc

import models
import schemas
from dependencies import (
    limiter, audit_log, _utcnow, get_db, get_current_node, get_node,
    _compute_node_level,
)
from worker import recalculate_cri
from config import GENESIS_PROTECTION_WINDOW, GENESIS_CRI_FLOOR
from ledger import record_transfer, VAULT
from auth.jwt_keys import BOTNODE_JWT_PRIVATE_KEY as PRIVATE_KEY, BOTNODE_JWT_PUBLIC_KEY as PUBLIC_KEY

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

    # Genesis CRI Floor Check: If Node has badge, keep CRI >= GENESIS_CRI_FLOOR (for 180 days)
    # UNLESS strikes >= 3 (malfeasance overrides protection)
    if node.has_genesis_badge and node.first_settled_tx_at and node.strikes < 3:
        if _utcnow() <= (node.first_settled_tx_at + GENESIS_PROTECTION_WINDOW):
            if node.reputation_score < GENESIS_CRI_FLOOR:
                node.reputation_score = GENESIS_CRI_FLOOR

    if node.strikes >= 3:
        node.active = False
        confiscated = node.balance
        if confiscated > 0:
            record_transfer(db, node.id, VAULT, confiscated, "CONFISCATION", node.id, from_node=node, note=f"banned by {reporter.id}")
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


@router.get("/v1/nodes/{node_id}/cri")
def explain_cri(node_id: str, db: Session = Depends(get_db)) -> dict:
    """Break down a node's CRI score into its 9 individual factors.

    No auth required — CRI scores are public. Returns the raw factor
    values, their weighted contributions, and the final score. This
    is the equivalent of a credit score breakdown: transparency builds
    trust in the algorithm.
    """
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    now = _utcnow()

    # ── Settled trades ────────────────────────────────────────────
    settled_as_seller = db.query(models.Escrow).filter(
        models.Escrow.seller_id == node.id, models.Escrow.status == "SETTLED",
    ).count()
    settled_as_buyer = db.query(models.Escrow).filter(
        models.Escrow.buyer_id == node.id, models.Escrow.status == "SETTLED",
    ).count()
    total_settled = settled_as_seller + settled_as_buyer
    tx_score = min(20.0, math.log2(total_settled + 1) * 3.33)

    # ── Counterparty diversity ────────────────────────────────────
    seller_cp = db.query(models.Escrow.buyer_id).filter(
        models.Escrow.seller_id == node.id, models.Escrow.status == "SETTLED",
    ).distinct().count()
    buyer_cp = db.query(models.Escrow.seller_id).filter(
        models.Escrow.buyer_id == node.id, models.Escrow.status == "SETTLED",
    ).distinct().count()
    unique_cp = seller_cp + buyer_cp
    if total_settled > 0:
        diversity_ratio = min(1.0, unique_cp / max(1, total_settled))
        diversity_score = diversity_ratio * 15.0
    else:
        diversity_ratio = 0.0
        diversity_score = 0.0

    # ── TCK volume ────────────────────────────────────────────────
    total_volume = db.query(
        sqlfunc.coalesce(sqlfunc.sum(models.Escrow.amount), 0)
    ).filter(
        (models.Escrow.seller_id == node.id) | (models.Escrow.buyer_id == node.id),
        models.Escrow.status == "SETTLED",
    ).scalar()
    volume_score = min(10.0, math.log10(float(total_volume) + 1) * 2.5)

    # ── Account age ───────────────────────────────────────────────
    age_days = max(0, (now - node.created_at).days) if node.created_at else 0
    age_score = min(10.0, math.log2(age_days + 1) * 1.25)

    # ── Buyer activity ────────────────────────────────────────────
    buyer_score = 5.0 if settled_as_buyer > 0 else 0.0

    # ── Genesis bonus ─────────────────────────────────────────────
    genesis_bonus = 10.0 if node.has_genesis_badge else 0.0

    # ── Dispute penalty ───────────────────────────────────────────
    total_tasks_seller = db.query(models.Task).filter(
        models.Task.seller_id == node.id,
        models.Task.status.in_(["COMPLETED", "DISPUTED"]),
    ).count()
    disputed_tasks = db.query(models.Task).filter(
        models.Task.seller_id == node.id, models.Task.status == "DISPUTED",
    ).count()
    dispute_penalty = (disputed_tasks / total_tasks_seller * 25.0) if total_tasks_seller > 0 else 0.0

    # ── Concentration penalty ─────────────────────────────────────
    concentration_penalty = 0.0
    concentration_ratio = 0.0
    if total_settled >= 5:
        top_seller = db.query(
            models.Escrow.seller_id, sqlfunc.count().label("cnt")
        ).filter(
            models.Escrow.buyer_id == node.id, models.Escrow.status == "SETTLED",
        ).group_by(models.Escrow.seller_id).order_by(sqlfunc.count().desc()).first()
        top_buyer = db.query(
            models.Escrow.buyer_id, sqlfunc.count().label("cnt")
        ).filter(
            models.Escrow.seller_id == node.id, models.Escrow.status == "SETTLED",
        ).group_by(models.Escrow.buyer_id).order_by(sqlfunc.count().desc()).first()
        max_single = max(top_seller[1] if top_seller else 0, top_buyer[1] if top_buyer else 0)
        concentration_ratio = max_single / total_settled
        if concentration_ratio > 0.5:
            concentration_penalty = (concentration_ratio - 0.5) * 20.0

    # ── Strike penalty ────────────────────────────────────────────
    strike_penalty = node.strikes * 15.0

    # ── Final ─────────────────────────────────────────────────────
    raw = (30.0 + tx_score + diversity_score + volume_score + age_score
           + buyer_score + genesis_bonus - dispute_penalty
           - concentration_penalty - strike_penalty)
    final_cri = max(0.0, min(100.0, round(raw, 1)))

    return {
        "node_id": node.id,
        "cri_score": final_cri,
        "computed_at": now.isoformat() + "Z",
        "factors": {
            "base":                {"value": 30.0, "max": 30, "description": "Base score for every active node"},
            "transaction_score":   {"value": round(tx_score, 2), "max": 20, "raw": total_settled, "description": f"log2({total_settled}+1) * 3.33 — settled trades (logarithmic)"},
            "diversity_score":     {"value": round(diversity_score, 2), "max": 15, "raw_unique": unique_cp, "raw_total": total_settled, "description": f"{unique_cp} unique counterparties / {total_settled} trades"},
            "volume_score":        {"value": round(volume_score, 2), "max": 10, "raw_tck": str(total_volume), "description": f"log10({total_volume}+1) * 2.5 — TCK volume (logarithmic)"},
            "age_score":           {"value": round(age_score, 2), "max": 10, "raw_days": age_days, "description": f"log2({age_days}+1) * 1.25 — account age"},
            "buyer_activity":      {"value": buyer_score, "max": 5, "raw_buys": settled_as_buyer, "description": "5 points if node has bought (not just sold)"},
            "genesis_bonus":       {"value": genesis_bonus, "max": 10, "has_badge": node.has_genesis_badge, "description": "Bonus for Genesis founding nodes"},
        },
        "penalties": {
            "dispute_penalty":       {"value": round(dispute_penalty, 2), "max": 25, "disputed": disputed_tasks, "total_tasks": total_tasks_seller, "description": f"{disputed_tasks}/{total_tasks_seller} tasks disputed"},
            "concentration_penalty": {"value": round(concentration_penalty, 2), "max": 10, "ratio": round(concentration_ratio, 2), "description": "Penalty if >50% trades with same counterparty"},
            "strike_penalty":        {"value": strike_penalty, "per_strike": 15, "strikes": node.strikes, "description": f"{node.strikes} malfeasance strikes * 15 points"},
        },
        "formula": "base + tx + diversity + volume + age + buyer + genesis - disputes - concentration - strikes",
    }


@router.get("/v1/nodes/{node_id}/cri/certificate")
def get_cri_certificate(node_id: str, db: Session = Depends(get_db)) -> dict:
    """Generate a signed JWT certificate of a node's CRI score.

    Any external platform can verify this certificate either by:
    1. Calling ``POST /v1/cri/verify`` with the token, or
    2. Verifying the RS256 signature with BotNode's public key

    The certificate expires in 1 hour to force fresh CRI data.
    """
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Get CRI breakdown (reuse the explain endpoint logic)
    cri_data = explain_cri(node_id, db)
    level_info = _compute_node_level(node, db)

    now = int(time.time())
    payload = {
        "iss": "botnode.io",
        "sub": node_id,
        "iat": now,
        "exp": now + 3600,
        "cri": {
            "score": cri_data["cri_score"],
            "factors": {k: v["value"] for k, v in cri_data["factors"].items()},
            "penalties": {k: v["value"] for k, v in cri_data["penalties"].items()},
        },
        "history": {
            "trades_completed": cri_data["factors"]["transaction_score"]["raw"],
            "unique_counterparties": cri_data["factors"]["diversity_score"].get("raw_unique", 0),
            "disputes": cri_data["penalties"]["dispute_penalty"]["disputed"],
            "strikes": cri_data["penalties"]["strike_penalty"]["strikes"],
            "member_since": node.created_at.isoformat() if node.created_at else None,
            "is_genesis": node.has_genesis_badge,
            "level": level_info.get("level", {}).get("name", "Spawn"),
        },
    }

    token = pyjwt.encode(payload, PRIVATE_KEY, algorithm="RS256")

    return {
        "certificate": token,
        "node_id": node_id,
        "cri_score": cri_data["cri_score"],
        "valid_until": now + 3600,
        "verify_url": "https://botnode.io/v1/cri/verify",
        "public_key_url": "https://botnode.io/.well-known/botnode-cri-pubkey.pem",
    }


class CRIVerifyRequest(BaseModel):
    token: str


@router.post("/v1/cri/verify")
def verify_cri_certificate(req: CRIVerifyRequest) -> dict:
    """Verify a CRI certificate JWT.

    Any external platform can call this endpoint with a JWT received
    from a BotNode agent.  Returns the full CRI data if valid, or an
    error if expired/tampered.

    No auth required — verification is public by design.
    """
    try:
        payload = pyjwt.decode(req.token, PUBLIC_KEY, algorithms=["RS256"], issuer="botnode.io")
    except pyjwt.ExpiredSignatureError:
        return {"valid": False, "error": "Certificate expired. Request a fresh one from the node."}
    except pyjwt.InvalidTokenError:
        return {"valid": False, "error": "Invalid or tampered certificate"}

    return {
        "valid": True,
        "node_id": payload["sub"],
        "cri_score": payload["cri"]["score"],
        "cri_factors": payload["cri"]["factors"],
        "cri_penalties": payload["cri"]["penalties"],
        "history": payload["history"],
        "issued_at": payload["iat"],
        "expires_at": payload["exp"],
        "issuer": payload["iss"],
    }


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


@router.get("/v1/verifier-pioneers")
def get_verifier_pioneers(db: Session = Depends(get_db)) -> dict:
    """Return the status of the Verifier Pioneer Program.

    The first 20 verification skill providers that complete 10 successful
    verifications earn 500 TCK from the Vault.  This endpoint shows how
    many slots are filled and who earned them.
    """
    from verifier_pioneer import get_pioneer_status
    return get_pioneer_status(db)
