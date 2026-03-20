"""Automated dispute resolution engine for BotNode.

Evaluates completed tasks against four deterministic rules before
settlement proceeds.  If any rule fires, the escrow is auto-refunded
and the decision is recorded in ``dispute_rules_log`` for audit.

Rules (evaluated in order — first match wins):
    1. **PROOF_MISSING** — Task marked COMPLETED but ``output_data`` is empty.
    2. **SCHEMA_MISMATCH** — Output doesn't validate against the skill's
       ``output_schema`` (when defined in ``metadata_json``).
    3. **VALIDATOR_FAILED** — Output fails one or more protocol validators
       attached to the skill.
    4. **TIMEOUT_NON_DELIVERY** — Task still OPEN/PENDING after 72 h
       (handled by settlement_worker Phase 2).

Integration point: called by ``auto_settle_escrows`` in ``routers/admin.py``
*before* each settlement.  If the engine returns a dispute, the escrow is
refunded instead of settled.

All functions are synchronous (matching the rest of the codebase) and
receive an explicit ``Session`` so they participate in the caller's
transaction.

**Oracle Problem context:** The dispute engine handles only binary,
deterministic cases. Subjective quality evaluation is delegated to
Quality Markets (verifier skills competing on CRI). This separation
follows the "Trust or Escalate" architecture (ICLR 2025) and the
BIS 2023 prescription for hybrid oracle architectures. See whitepaper
Section 10.8 for the full four-layer quality assurance stack and
its academic foundations (Hart & Moore, Akerlof, Coase, Schelling).
"""

import json
import logging
from datetime import timedelta
from decimal import Decimal
from typing import Optional, Tuple

import jsonschema
from sqlalchemy.orm import Session

import models
from config import PENDING_ESCROW_TIMEOUT
from dependencies import _utcnow
from ledger import record_transfer

logger = logging.getLogger("botnode.disputes")

# ---------------------------------------------------------------------------
# Reason codes
# ---------------------------------------------------------------------------

SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
TIMEOUT_NON_DELIVERY = "TIMEOUT_NON_DELIVERY"
PROOF_MISSING = "PROOF_MISSING"
VALIDATOR_FAILED = "VALIDATOR_FAILED"


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------

def evaluate_task(
    task: models.Task,
    skill: Optional[models.Skill],
) -> Tuple[bool, Optional[str], Optional[dict]]:
    """Evaluate a task against the four auto-dispute rules.

    Returns
    -------
    (should_dispute, reason_code, details)
        ``(False, None, None)`` means the task passed all rules and
        settlement should proceed normally.

        ``(True, "SCHEMA_MISMATCH", {...})`` means the task failed a
        rule and should be auto-refunded.
    """
    # ── Rule 1: PROOF_MISSING ──────────────────────────────────────────
    # Task is marked COMPLETED but has no output at all.
    if task.status == "COMPLETED":
        output = task.output_data
        if output is None or output == {} or output == "":
            return (
                True,
                PROOF_MISSING,
                {"task_status": task.status, "output_data": None},
            )

    # ── Rule 2: SCHEMA_MISMATCH ───────────────────────────────────────
    # If the skill defines an output_schema in its metadata, validate.
    if task.status == "COMPLETED" and skill and skill.metadata_json:
        metadata = skill.metadata_json
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}

        output_schema = metadata.get("output_schema")
        if output_schema:
            output = task.output_data
            if isinstance(output, str):
                try:
                    output = json.loads(output)
                except (json.JSONDecodeError, TypeError):
                    return (
                        True,
                        SCHEMA_MISMATCH,
                        {
                            "error": "output_not_valid_json",
                            "output_preview": str(output)[:200],
                        },
                    )

            try:
                jsonschema.validate(instance=output, schema=output_schema)
            except jsonschema.ValidationError as exc:
                return (
                    True,
                    SCHEMA_MISMATCH,
                    {
                        "schema_error": str(exc.message),
                        "path": [str(p) for p in exc.absolute_path],
                        "expected": str(exc.schema)[:200],
                        "got": str(exc.instance)[:200],
                    },
                )

    # ── Rule 3: PROTOCOL VALIDATORS ──────────────────────────────────
    # If the skill defines a validators array in metadata, run them.
    if task.status == "COMPLETED" and skill and skill.metadata_json:
        metadata = skill.metadata_json
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}

        validators = metadata.get("validators", [])
        if validators:
            from protocol_validators import run_protocol_validators
            output = task.output_data or {}
            passed, reason, details = run_protocol_validators(output, validators)
            if not passed:
                return (True, VALIDATOR_FAILED, details)

    # ── All rules passed ──────────────────────────────────────────────
    return (False, None, None)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def execute_auto_refund(
    db: Session,
    task: models.Task,
    escrow: models.Escrow,
    reason_code: str,
    details: Optional[dict],
) -> None:
    """Refund the buyer and log the automated dispute decision.

    Performs three operations inside the caller's transaction:
    1. Records the decision in ``dispute_rules_log``.
    2. Updates the escrow to REFUNDED with the reason code.
    3. Returns the locked TCK to the buyer via the double-entry ledger.
    """
    # 1. Audit log entry
    log_entry = models.DisputeRulesLog(
        task_id=task.id,
        escrow_id=escrow.id,
        rule_applied=reason_code,
        rule_details=details,
        action_taken="AUTO_REFUND",
    )
    db.add(log_entry)

    # 2. Update escrow
    escrow.status = "REFUNDED"
    escrow.dispute_reason = reason_code

    # 3. Refund buyer (with row lock to prevent double-refund race)
    buyer = db.query(models.Node).filter(models.Node.id == escrow.buyer_id).with_for_update().first()
    if buyer:
        record_transfer(
            db,
            from_account="ESCROW:" + escrow.id,
            to_account=buyer.id,
            amount=Decimal(str(escrow.amount)),
            reference_type="ESCROW_REFUND",
            reference_id=escrow.id,
            to_node=buyer,
            note=f"AUTO_REFUND:{reason_code}",
        )

    logger.info(
        "Auto-dispute: task=%s reason=%s amount=%s buyer=%s",
        task.id,
        reason_code,
        escrow.amount,
        escrow.buyer_id,
    )


def run_dispute_check(
    db: Session,
    task: models.Task,
    escrow: models.Escrow,
    skill: Optional[models.Skill],
) -> bool:
    """Convenience wrapper: evaluate + execute if needed.

    Returns ``True`` if the task was auto-refunded (settlement should
    be skipped), ``False`` if it passed all rules (proceed to settle).
    """
    should_dispute, reason_code, details = evaluate_task(task, skill)
    if should_dispute:
        execute_auto_refund(db, task, escrow, reason_code, details)
        return True
    return False
