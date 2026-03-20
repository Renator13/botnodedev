"""Bounty board endpoints — create, browse, submit, award, and cancel bounties."""

from decimal import Decimal
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

import models
import schemas
from dependencies import (
    get_db, get_current_node, _utcnow, check_level_gate, logger,
)
from config import PROTOCOL_TAX_RATE
from ledger import record_transfer, VAULT
from worker import recalculate_cri

router = APIRouter(tags=["bounty"])


@router.post("/v1/bounties")
def create_bounty(
    body: schemas.BountyCreate,
    node: models.Node = Depends(get_current_node),
    db: Session = Depends(get_db),
) -> dict:
    """Create a new bounty and lock the reward in escrow.

    Auth: JWT or API key.  Soft gate: Worker (level >= 1).
    The reward TCK is transferred from the creator's balance into a
    BOUNTY escrow account.
    """
    # Soft level gate — Worker (level 1)
    gate = check_level_gate(node, 1, db)
    if gate:
        raise HTTPException(status_code=403, detail=gate["error"])

    reward = Decimal(str(body.reward_tck))

    # M-02 fix: row lock to prevent race condition on balance check
    node = db.query(models.Node).filter(models.Node.id == node.id).with_for_update().first()
    if node.balance < reward:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    bounty = models.Bounty(
        creator_node_id=node.id,
        title=body.title,
        description=body.description,
        reward_tck=reward,
        category=body.category,
        tags=body.tags,
    )

    if body.deadline_days:
        bounty.deadline_at = _utcnow() + timedelta(days=body.deadline_days)

    db.add(bounty)
    db.flush()  # get bounty.id

    escrow_ref = "ESCROW:BOUNTY:" + bounty.id
    bounty.escrow_reference = escrow_ref

    record_transfer(
        db, node.id, escrow_ref, reward,
        "BOUNTY_HOLD", bounty.id, from_node=node,
    )

    db.commit()
    logger.info("Bounty %s created by %s for %s TCK", bounty.id, node.id, reward)

    return {
        "bounty_id": bounty.id,
        "title": bounty.title,
        "reward_tck": str(bounty.reward_tck),
        "category": bounty.category,
        "status": bounty.status,
        "deadline_at": bounty.deadline_at.isoformat() if bounty.deadline_at else None,
        "escrow_reference": bounty.escrow_reference,
        "created_at": bounty.created_at.isoformat() if bounty.created_at else None,
    }


@router.get("/v1/bounties")
def list_bounties(
    status: str = Query("open", pattern=r'^(open|awarded|cancelled|expired|all)$'),
    category: str = Query(None),
    min_reward: float = Query(None, ge=0),
    sort: str = Query("newest", pattern=r'^(newest|reward|deadline)$'),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """List bounties with optional filters.

    Public endpoint — no authentication required.  Returns a summary
    for each bounty (no full description).
    """
    query = db.query(models.Bounty)

    if status != "all":
        query = query.filter(models.Bounty.status == status)
    if category:
        query = query.filter(models.Bounty.category == category)
    if min_reward is not None:
        query = query.filter(models.Bounty.reward_tck >= Decimal(str(min_reward)))

    if sort == "reward":
        query = query.order_by(models.Bounty.reward_tck.desc())
    elif sort == "deadline":
        query = query.order_by(models.Bounty.deadline_at.asc())
    else:
        query = query.order_by(models.Bounty.created_at.desc())

    total = query.count()
    bounties = query.offset(offset).limit(limit).all()

    results = []
    for b in bounties:
        sub_count = db.query(func.count(models.BountySubmission.id)).filter(
            models.BountySubmission.bounty_id == b.id,
        ).scalar()
        creator = db.query(models.Node).filter(models.Node.id == b.creator_node_id).first()
        results.append({
            "bounty_id": b.id,
            "title": b.title,
            "reward_tck": str(b.reward_tck),
            "category": b.category,
            "status": b.status,
            "tags": b.tags,
            "submission_count": sub_count,
            "creator_node_id": b.creator_node_id,
            "creator_cri": float(creator.cri_score) if creator and creator.cri_score else 0.0,
            "deadline_at": b.deadline_at.isoformat() if b.deadline_at else None,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        })

    return {"bounties": results, "total": total, "limit": limit, "offset": offset}


@router.get("/v1/bounties/{bounty_id}")
def get_bounty_detail(bounty_id: str, db: Session = Depends(get_db)) -> dict:
    """Return full bounty detail including description and submissions.

    Public endpoint — no authentication required.
    """
    bounty = db.query(models.Bounty).filter(models.Bounty.id == bounty_id).first()
    if not bounty:
        raise HTTPException(status_code=404, detail="Bounty not found")

    submissions = db.query(models.BountySubmission).filter(
        models.BountySubmission.bounty_id == bounty_id,
    ).order_by(models.BountySubmission.created_at.desc()).all()

    creator = db.query(models.Node).filter(models.Node.id == bounty.creator_node_id).first()

    return {
        "bounty_id": bounty.id,
        "title": bounty.title,
        "description": bounty.description,
        "reward_tck": str(bounty.reward_tck),
        "category": bounty.category,
        "status": bounty.status,
        "tags": bounty.tags,
        "creator_node_id": bounty.creator_node_id,
        "creator_cri": float(creator.cri_score) if creator and creator.cri_score else 0.0,
        "deadline_at": bounty.deadline_at.isoformat() if bounty.deadline_at else None,
        "winner_node_id": bounty.winner_node_id,
        "winner_submission_id": bounty.winner_submission_id,
        "created_at": bounty.created_at.isoformat() if bounty.created_at else None,
        "awarded_at": bounty.awarded_at.isoformat() if bounty.awarded_at else None,
        "submissions": [
            {
                "id": s.id,
                "solver_node_id": s.solver_node_id,
                "content": s.content,
                "proof_url": s.proof_url,
                "skill_id": s.skill_id,
                "status": s.status,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in submissions
        ],
    }


@router.post("/v1/bounties/{bounty_id}/submissions")
def submit_solution(
    bounty_id: str,
    body: schemas.BountySubmissionCreate,
    node: models.Node = Depends(get_current_node),
    db: Session = Depends(get_db),
) -> dict:
    """Submit a solution to an open bounty.

    Auth: JWT or API key.  Soft gate: Worker (level >= 1).
    Validates that the bounty is open, the solver is not the creator,
    and the solver has at most one pending submission per bounty.
    """
    # Soft level gate — Worker (level 1)
    gate = check_level_gate(node, 1, db)
    if gate:
        raise HTTPException(status_code=403, detail=gate["error"])

    bounty = db.query(models.Bounty).filter(models.Bounty.id == bounty_id).first()
    if not bounty:
        raise HTTPException(status_code=404, detail="Bounty not found")
    if bounty.status != "open":
        raise HTTPException(status_code=400, detail="Bounty is not open")
    if bounty.creator_node_id == node.id:
        raise HTTPException(status_code=400, detail="Cannot submit to your own bounty")

    existing = db.query(models.BountySubmission).filter(
        models.BountySubmission.bounty_id == bounty_id,
        models.BountySubmission.solver_node_id == node.id,
        models.BountySubmission.status == "pending",
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="You already have a pending submission for this bounty")

    submission = models.BountySubmission(
        bounty_id=bounty_id,
        solver_node_id=node.id,
        content=body.content,
        proof_url=body.proof_url,
        skill_id=body.skill_id,
    )
    db.add(submission)
    db.commit()

    return {
        "submission_id": submission.id,
        "bounty_id": bounty_id,
        "status": submission.status,
        "created_at": submission.created_at.isoformat() if submission.created_at else None,
    }


@router.post("/v1/bounties/{bounty_id}/award")
def award_bounty(
    bounty_id: str,
    body: schemas.BountyAward,
    node: models.Node = Depends(get_current_node),
    db: Session = Depends(get_db),
) -> dict:
    """Accept a submission and release the bounty reward to the solver.

    Auth: JWT or API key (must be the bounty creator).
    The solver receives reward minus 3% protocol tax.  All other pending
    submissions are rejected.
    """
    bounty = db.query(models.Bounty).filter(models.Bounty.id == bounty_id).first()
    if not bounty:
        raise HTTPException(status_code=404, detail="Bounty not found")
    if bounty.creator_node_id != node.id:
        raise HTTPException(status_code=403, detail="Only the bounty creator can award")
    if bounty.status != "open":
        raise HTTPException(status_code=400, detail="Bounty is not open")

    submission = db.query(models.BountySubmission).filter(
        models.BountySubmission.id == body.submission_id,
        models.BountySubmission.bounty_id == bounty_id,
    ).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    if submission.status != "pending":
        raise HTTPException(status_code=400, detail="Submission is not pending")

    solver = db.query(models.Node).filter(models.Node.id == submission.solver_node_id).first()
    if not solver:
        raise HTTPException(status_code=404, detail="Solver node not found")

    now = _utcnow()
    escrow_ref = bounty.escrow_reference or ("ESCROW:BOUNTY:" + bounty.id)
    reward = bounty.reward_tck
    tax = reward * PROTOCOL_TAX_RATE
    payout = reward - tax

    # Release reward to solver (minus tax)
    record_transfer(db, escrow_ref, solver.id, payout, "BOUNTY_RELEASE", bounty.id, to_node=solver)
    # Tax to vault
    record_transfer(db, escrow_ref, VAULT, tax, "PROTOCOL_TAX", bounty.id)

    # Update bounty state
    bounty.status = "awarded"
    bounty.winner_node_id = solver.id
    bounty.winner_submission_id = submission.id
    bounty.awarded_at = now

    # Accept winning submission, reject others
    submission.status = "accepted"
    submission.reviewed_at = now

    other_subs = db.query(models.BountySubmission).filter(
        models.BountySubmission.bounty_id == bounty_id,
        models.BountySubmission.id != submission.id,
        models.BountySubmission.status == "pending",
    ).all()
    for s in other_subs:
        s.status = "rejected"
        s.reviewed_at = now

    # Recalculate solver CRI
    recalculate_cri(solver, db)

    db.commit()
    logger.info("Bounty %s awarded to %s, payout=%s, tax=%s", bounty.id, solver.id, payout, tax)

    return {
        "bounty_id": bounty.id,
        "status": "awarded",
        "winner_node_id": solver.id,
        "payout": str(payout),
        "tax": str(tax),
        "awarded_at": now.isoformat(),
    }


@router.post("/v1/bounties/{bounty_id}/cancel")
def cancel_bounty(
    bounty_id: str,
    node: models.Node = Depends(get_current_node),
    db: Session = Depends(get_db),
) -> dict:
    """Cancel an open bounty and refund the reward to the creator.

    Auth: JWT or API key (must be the bounty creator).
    All pending submissions are rejected.
    """
    bounty = db.query(models.Bounty).filter(models.Bounty.id == bounty_id).first()
    if not bounty:
        raise HTTPException(status_code=404, detail="Bounty not found")
    if bounty.creator_node_id != node.id:
        raise HTTPException(status_code=403, detail="Only the bounty creator can cancel")
    if bounty.status != "open":
        raise HTTPException(status_code=400, detail="Bounty is not open")

    now = _utcnow()
    escrow_ref = bounty.escrow_reference or ("ESCROW:BOUNTY:" + bounty.id)

    creator = db.query(models.Node).filter(models.Node.id == node.id).first()
    record_transfer(db, escrow_ref, node.id, bounty.reward_tck, "BOUNTY_REFUND", bounty.id, to_node=creator)

    bounty.status = "cancelled"
    bounty.cancelled_at = now

    # Reject all pending submissions
    pending_subs = db.query(models.BountySubmission).filter(
        models.BountySubmission.bounty_id == bounty_id,
        models.BountySubmission.status == "pending",
    ).all()
    for s in pending_subs:
        s.status = "rejected"
        s.reviewed_at = now

    db.commit()
    logger.info("Bounty %s cancelled, refund to %s", bounty.id, node.id)

    return {
        "bounty_id": bounty.id,
        "status": "cancelled",
        "refunded_tck": str(bounty.reward_tck),
        "cancelled_at": now.isoformat(),
    }
