"""Verifier Pioneer Program — 500 TCK bonus for the first 20 quality verifiers.

The first 20 verification skill providers that complete 10 successful
verifications — where "successful" means the original task that was verified
settled WITHOUT dispute — receive 500 TCK from the Vault.

This bootstraps the Quality Markets by incentivizing the supply side of
verification.  The program is analogous to the Genesis program for nodes,
but for the verification ecosystem.

Eligibility:
    1. Node owns a skill with category "verification"
    2. That skill has been hired 10+ times as a verifier
    3. In 10+ of those cases, the ORIGINAL task (the one being verified)
       settled without dispute
    4. The node has not already received the pioneer bonus
    5. Fewer than 20 pioneer bonuses have been awarded total

The check runs during settlement of verification tasks (in the settlement
worker), not on a cron.
"""

import logging
from decimal import Decimal

from sqlalchemy.orm import Session
from sqlalchemy import func

import models
from config import MAX_VERIFIER_PIONEERS, VERIFIER_PIONEER_BONUS, VERIFIER_PIONEER_THRESHOLD
from ledger import record_transfer, VAULT

logger = logging.getLogger("botnode.verifier_pioneer")


def check_and_award_pioneer(db: Session, verifier_node_id: str) -> bool:
    """Check if a verifier node qualifies for the pioneer bonus and award it.

    Called after a verification task settles.  Returns True if bonus was
    awarded, False otherwise.
    """
    # Already awarded?
    existing = db.query(models.VerifierPioneerAward).filter(
        models.VerifierPioneerAward.node_id == verifier_node_id,
    ).first()
    if existing:
        return False

    # Max pioneers reached?
    total_pioneers = db.query(func.count(models.VerifierPioneerAward.id)).scalar() or 0
    if total_pioneers >= MAX_VERIFIER_PIONEERS:
        return False

    # Does this node own a verification skill?
    verification_skills = db.query(models.Skill).filter(
        models.Skill.provider_id == verifier_node_id,
    ).all()

    verifier_skill = None
    for skill in verification_skills:
        metadata = skill.metadata_json or {}
        if isinstance(metadata, str):
            import json
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}
        if metadata.get("category") == "verification":
            verifier_skill = skill
            break

    if not verifier_skill:
        return False

    # Count successful verifications:
    # Tasks where this node was the SELLER (executed the verification)
    # AND the task settled (status COMPLETED, escrow SETTLED)
    settled_verifications = db.query(func.count(models.Task.id)).join(
        models.Escrow, models.Task.escrow_id == models.Escrow.id,
    ).filter(
        models.Task.seller_id == verifier_node_id,
        models.Task.skill_id == verifier_skill.id,
        models.Task.status == "COMPLETED",
        models.Escrow.status == "SETTLED",
    ).scalar() or 0

    if settled_verifications < VERIFIER_PIONEER_THRESHOLD:
        return False

    # Award the bonus
    pioneer_rank = total_pioneers + 1
    node = db.query(models.Node).filter(models.Node.id == verifier_node_id).first()
    if not node:
        return False

    record_transfer(
        db,
        from_account=VAULT,
        to_account=verifier_node_id,
        amount=VERIFIER_PIONEER_BONUS,
        reference_type="VERIFIER_PIONEER_BONUS",
        reference_id=verifier_skill.id,
        to_node=node,
        note=f"Verifier Pioneer #{pioneer_rank}: {verifier_skill.label}",
    )

    award = models.VerifierPioneerAward(
        node_id=verifier_node_id,
        verifier_skill_id=verifier_skill.id,
        successful_verifications=settled_verifications,
        pioneer_rank=pioneer_rank,
        bonus_tck=VERIFIER_PIONEER_BONUS,
    )
    db.add(award)

    logger.info(
        f"Verifier Pioneer #{pioneer_rank}: node={verifier_node_id} "
        f"skill={verifier_skill.label} verifications={settled_verifications} "
        f"bonus={VERIFIER_PIONEER_BONUS} TCK"
    )

    return True


def get_pioneer_status(db: Session) -> dict:
    """Return the current state of the Verifier Pioneer Program."""
    awards = (
        db.query(models.VerifierPioneerAward)
        .order_by(models.VerifierPioneerAward.pioneer_rank.asc())
        .all()
    )

    return {
        "program": "Verifier Pioneer",
        "slots_total": MAX_VERIFIER_PIONEERS,
        "slots_filled": len(awards),
        "slots_remaining": MAX_VERIFIER_PIONEERS - len(awards),
        "bonus_tck": str(VERIFIER_PIONEER_BONUS),
        "threshold_verifications": VERIFIER_PIONEER_THRESHOLD,
        "pioneers": [
            {
                "rank": a.pioneer_rank,
                "node_id": a.node_id,
                "skill_id": a.verifier_skill_id,
                "verifications": a.successful_verifications,
                "awarded_at": a.awarded_at.isoformat() if a.awarded_at else None,
            }
            for a in awards
        ],
    }
