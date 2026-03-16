"""Node lifecycle endpoints: registration, verification, profiles, and badges."""

import math
import time
import random
import secrets
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, HTTPException, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

import models
import schemas
from dependencies import (
    limiter, audit_log, _utcnow, pwd_context,
    get_db, get_current_node, is_prime, generate_status_badge_svg,
    BASE_URL,
)
from auth.jwt_tokens import issue_access_token
from worker import check_and_award_genesis_badges, recalculate_cri
from config import INITIAL_NODE_BALANCE, CHALLENGE_TTL_SECONDS
from ledger import record_transfer, MINT

router = APIRouter(tags=["nodes"])


@router.post("/v1/node/register")
@limiter.limit("5/minute")
def register_node(data: schemas.RegisterRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Begin node registration by issuing a unique prime-sum challenge.

    The challenge payload is a random mix of primes and composites.  The
    caller must sum the primes, multiply by 0.5, and POST the result to
    ``/v1/node/verify`` within 30 seconds.  Each ``node_id`` can only have
    one pending challenge at a time.

    Rate limit: 5 requests/minute per IP.
    """
    # Prevent duplicate registration of the same ID
    existing = db.query(models.Node).filter(models.Node.id == data.node_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Node ID already registered")

    # Optional Genesis early-access linkage via signup_token
    if data.signup_token:
        signup = db.query(models.EarlyAccessSignup).filter(
            models.EarlyAccessSignup.signup_token == data.signup_token
        ).first()
        if not signup:
            raise HTTPException(status_code=400, detail="Invalid signup_token: no matching early access signup found")
        if signup.linked_node_id is not None:
            raise HTTPException(status_code=400, detail="Signup token already linked to a node")

    # Generate a unique random challenge per registration attempt
    primes_pool = [2,3,5,7,11,13,17,19,23,29,31,37,41,43,47,53,59,61,67,71,73,79,83,89,97]
    composites_pool = [4,6,8,9,10,12,14,15,16,18,20,21,22,24,25,26,27,28,30,33,34,35,36,38,39,40,42,44,45,46,48,49,50,51,52,54,55,56,57,58,60,62,63,64,65,66,68,69,70,72,74,75,76,77,78,80,81,82,84,85,86,87,88,90,91,92,93,94,95,96,98,99]
    selected_primes = random.sample(primes_pool, random.randint(3, 7))
    selected_composites = random.sample(composites_pool, random.randint(3, 7))
    challenge_payload = selected_primes + selected_composites
    random.shuffle(challenge_payload)

    expected_result = sum(selected_primes) * 0.5
    expires_at = _utcnow() + timedelta(seconds=CHALLENGE_TTL_SECONDS)

    # Upsert: delete any old challenge for this node_id, then insert new one
    db.query(models.PendingChallenge).filter(
        models.PendingChallenge.node_id == data.node_id
    ).delete()
    db.add(models.PendingChallenge(
        node_id=data.node_id,
        payload=challenge_payload,
        expected_solution=expected_result,
        expires_at=expires_at,
    ))
    db.commit()

    return {
        "status": "NODE_PENDING_VERIFICATION",
        "node_id": data.node_id,
        "wallet": {"initial_balance": "100.00", "state": "FROZEN_UNTIL_CHALLENGE_SOLVED"},
        "verification_challenge": {
            "type": "PRIME_SUM_HASH",
            "payload": challenge_payload,
            "instruction": "Sum all prime numbers in 'payload', multiply by 0.5, and POST to /v1/node/verify",
            "timeout_ms": 30000,
            "ts": time.time()
        }
    }


@router.post("/v1/node/verify")
@limiter.limit("10/minute")
def verify_node(data: schemas.VerifyRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Complete registration by solving the prime-sum challenge.

    On success the node is persisted with an initial balance of 100 TCK,
    a PBKDF2-hashed API key is generated, and a short-lived RS256 JWT is
    returned.  If a ``signup_token`` is provided the node is linked to its
    early-access signup record (required for Genesis badge eligibility).

    Rate limit: 10 requests/minute per IP.
    """
    # Validate against the stored per-node challenge (DB-backed)
    challenge = db.query(models.PendingChallenge).filter(
        models.PendingChallenge.node_id == data.node_id
    ).first()
    if not challenge:
        raise HTTPException(status_code=400, detail="No pending challenge — call /v1/node/register first")
    if _utcnow() > challenge.expires_at:
        db.delete(challenge)
        db.commit()
        raise HTTPException(status_code=400, detail="Challenge expired — register again")

    expected_result = challenge.expected_solution

    # Remove the challenge row now that it's been consumed
    db.delete(challenge)
    db.flush()
    if not math.isclose(data.solution, expected_result, rel_tol=1e-9, abs_tol=0.01):
        raise HTTPException(status_code=400, detail="Challenge failed: Incorrect solution")

    # Optional Genesis early-access linkage via signup_token
    signup = None
    if getattr(data, "signup_token", None):
        signup = db.query(models.EarlyAccessSignup).filter(
            models.EarlyAccessSignup.signup_token == data.signup_token
        ).first()
        if not signup:
            raise HTTPException(status_code=400, detail="Invalid signup_token: no matching early access signup found")
        if signup.linked_node_id is not None:
            raise HTTPException(status_code=400, detail="Signup token already linked to a node")

    # Generate API Key: bn_{node_id}_{secret}
    secret = secrets.token_hex(16) # 32 chars
    raw_api_key = f"bn_{data.node_id}_{secret}"
    hashed_secret = pwd_context.hash(secret)

    new_node = models.Node(
        id=data.node_id,
        api_key_hash=hashed_secret,
        ip_address=request.client.host,
        balance=Decimal("0"),
        signup_token=data.signup_token if getattr(data, "signup_token", None) else None,
    )
    db.add(new_node)
    db.flush()

    # Mint initial balance through the ledger so books balance from day zero
    record_transfer(db, MINT, new_node.id, INITIAL_NODE_BALANCE, "REGISTRATION_CREDIT", new_node.id, to_node=new_node)

    # If we have a valid signup_token, link the EarlyAccessSignup to this node
    if signup is not None:
        signup.linked_node_id = new_node.id
        signup.status = "linked"

    db.commit()

    audit_log.info(f"NODE_REGISTERED node={data.node_id} ip={request.client.host}")
    return {
        "status": "NODE_ACTIVE",
        "message": f"Welcome to the cluster, {data.node_id}.",
        "api_key": raw_api_key,
        "session_token": issue_access_token(data.node_id, role="node"),
        "unlocked_balance": "100.00"
    }


@router.get("/v1/nodes/{node_id}")
def get_node_profile(node_id: str, db: Session = Depends(get_db)) -> dict:
    """Return a node's public profile: reputation, strikes, and skill catalogue.

    Auth: none (public endpoint).
    """
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node: raise HTTPException(status_code=404, detail="Node not found")

    skills = db.query(models.Skill).filter(models.Skill.provider_id == node_id).all()

    return {
        "node_id": node.id,
        "reputation": node.reputation_score,
        "strikes": node.strikes,
        "active": node.active,
        "member_since": node.created_at.isoformat(),
        "skills": [
            {"id": s.id, "label": s.label, "price": str(s.price_tck)} for s in skills
        ]
    }


@router.get("/v1/node/{node_id}/badge.svg")
def get_node_badge_svg(node_id: str, db: Session = Depends(get_db)) -> Response:
    """Dynamic SVG status badge for a node.

    Intended usage: embeddable badge (e.g. in READMEs or dashboards).
    """
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Genesis rank (only if badge has been awarded)
    rank = node.genesis_rank if node.has_genesis_badge and node.genesis_rank is not None else None

    # TX count: number of settled escrows where this node is the seller
    tx_count = db.query(models.Escrow).filter(
        models.Escrow.seller_id == node_id,
        models.Escrow.status == "SETTLED",
    ).count()

    # Skills count: how many skills this node provides
    skills_count = db.query(models.Skill).filter(models.Skill.provider_id == node_id).count()

    # Active days: days since node creation (minimum 0)
    delta = _utcnow() - node.created_at
    active_days = max(0, delta.days)

    # CRI: use persisted score from worker, recalculate if stale (>1h) or missing
    cri_val = node.cri_score
    if cri_val is None or node.cri_updated_at is None or (_utcnow() - node.cri_updated_at).total_seconds() > 3600:
        cri_val = recalculate_cri(node, db)
        db.commit()
    cri = int(round(cri_val))

    stats = {
        "rank": rank,
        "cri": cri,
        "tx_count": tx_count,
        "active_days": active_days,
        "skills_count": skills_count,
    }

    svg = generate_status_badge_svg(node, stats)

    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    return Response(content=svg, media_type="image/svg+xml", headers=headers)


@router.post("/v1/early-access", response_model=schemas.EarlyAccessSignupResponse)
@limiter.limit("3/minute")
def early_access_signup(request: Request, payload: schemas.EarlyAccessSignupRequest, db: Session = Depends(get_db)) -> dict:
    """Register an email for the BotNode early access / Genesis waitlist.

    This is the A-step only: it creates a pre_eligible signup row and returns
    a stable signup_token. No node linking or status transitions yet.
    """
    # Basic email normalization & validation (Pydantic already validates format)
    email = payload.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email must not be empty")

    # Generate a unique signup token with `ea_` prefix
    # Use a short loop to avoid rare collisions at the DB level.
    for _ in range(5):
        candidate = f"ea_{secrets.token_urlsafe(16)}"
        existing = db.query(models.EarlyAccessSignup).filter(models.EarlyAccessSignup.signup_token == candidate).first()
        if not existing:
            signup_token = candidate
            break
    else:
        # Extremely unlikely: fallback if we somehow can't find a unique token
        raise HTTPException(status_code=500, detail="Could not generate unique signup token")

    signup = models.EarlyAccessSignup(
        signup_token=signup_token,
        email=email,
        node_name=payload.node_name,
        agent_type=payload.agent_type,
        primary_capability=payload.primary_capability,
        why_joining=payload.why_joining,
    )

    db.add(signup)
    db.commit()

    return schemas.EarlyAccessSignupResponse(signup_token=signup_token, status="pre_eligible")
