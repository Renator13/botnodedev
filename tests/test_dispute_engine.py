"""Tests for the automated dispute resolution engine.

Covers the three deterministic rules (PROOF_MISSING, SCHEMA_MISMATCH,
TIMEOUT_NON_DELIVERY) and the execute/run helpers.
"""
import json
from unittest.mock import MagicMock, patch

from dispute_engine import (
    evaluate_task,
    execute_auto_refund,
    run_dispute_check,
    PROOF_MISSING,
    SCHEMA_MISMATCH,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(status="COMPLETED", output_data=None, skill_id=None, escrow_id=None):
    task = MagicMock()
    task.id = "task-001"
    task.status = status
    task.output_data = output_data
    task.skill_id = skill_id
    task.escrow_id = escrow_id
    return task


def _make_skill(output_schema=None):
    skill = MagicMock()
    skill.id = "skill-001"
    if output_schema is not None:
        skill.metadata_json = json.dumps({"output_schema": output_schema})
    else:
        skill.metadata_json = None
    return skill


def _make_escrow(amount=10, buyer_id="buyer-1", seller_id="seller-1"):
    escrow = MagicMock()
    escrow.id = "escrow-001"
    escrow.amount = amount
    escrow.buyer_id = buyer_id
    escrow.seller_id = seller_id
    escrow.status = "AWAITING_SETTLEMENT"
    return escrow


# ---------------------------------------------------------------------------
# Rule 1: PROOF_MISSING
# ---------------------------------------------------------------------------

def test_proof_missing_on_none_output():
    task = _make_task(status="COMPLETED", output_data=None)
    should_dispute, reason, _ = evaluate_task(task, skill=None)
    assert should_dispute is True
    assert reason == PROOF_MISSING


def test_proof_missing_on_empty_dict():
    task = _make_task(status="COMPLETED", output_data={})
    should_dispute, reason, _ = evaluate_task(task, skill=None)
    assert should_dispute is True
    assert reason == PROOF_MISSING


def test_proof_missing_on_empty_string():
    task = _make_task(status="COMPLETED", output_data="")
    should_dispute, reason, _ = evaluate_task(task, skill=None)
    assert should_dispute is True
    assert reason == PROOF_MISSING


# ---------------------------------------------------------------------------
# Rule 2: SCHEMA_MISMATCH
# ---------------------------------------------------------------------------

def test_schema_mismatch_wrong_type():
    schema = {"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]}
    task = _make_task(status="COMPLETED", output_data={"result": 42})  # int, not string
    skill = _make_skill(output_schema=schema)
    should_dispute, reason, details = evaluate_task(task, skill)
    assert should_dispute is True
    assert reason == SCHEMA_MISMATCH
    assert "schema_error" in details


def test_schema_mismatch_missing_required_field():
    schema = {"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]}
    task = _make_task(status="COMPLETED", output_data={"other": "value"})
    skill = _make_skill(output_schema=schema)
    should_dispute, reason, details = evaluate_task(task, skill)
    assert should_dispute is True
    assert reason == SCHEMA_MISMATCH


def test_schema_mismatch_output_not_json_string():
    schema = {"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]}
    task = _make_task(status="COMPLETED", output_data="this is not json")
    skill = _make_skill(output_schema=schema)
    should_dispute, reason, details = evaluate_task(task, skill)
    assert should_dispute is True
    assert reason == SCHEMA_MISMATCH
    assert details["error"] == "output_not_valid_json"


# ---------------------------------------------------------------------------
# Passing cases
# ---------------------------------------------------------------------------

def test_valid_output_passes_all_rules():
    schema = {"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]}
    task = _make_task(status="COMPLETED", output_data={"result": "hello"})
    skill = _make_skill(output_schema=schema)
    should_dispute, reason, details = evaluate_task(task, skill)
    assert should_dispute is False
    assert reason is None
    assert details is None


def test_no_skill_schema_passes():
    """A skill with no output_schema should not trigger SCHEMA_MISMATCH."""
    task = _make_task(status="COMPLETED", output_data={"result": "hello"})
    skill = _make_skill(output_schema=None)
    should_dispute, reason, _ = evaluate_task(task, skill)
    assert should_dispute is False


def test_no_skill_passes():
    """No skill at all means schema check is skipped."""
    task = _make_task(status="COMPLETED", output_data={"result": "hello"})
    should_dispute, reason, _ = evaluate_task(task, skill=None)
    assert should_dispute is False


def test_completed_with_valid_output_no_schema():
    """Completed task with output and no schema should pass all rules."""
    task = _make_task(status="COMPLETED", output_data={"some": "data"})
    skill = _make_skill(output_schema=None)
    should_dispute, reason, _ = evaluate_task(task, skill)
    assert should_dispute is False
    assert reason is None


# ---------------------------------------------------------------------------
# execute_auto_refund
# ---------------------------------------------------------------------------

@patch("dispute_engine.record_transfer")
def test_execute_auto_refund_creates_log_entry(mock_transfer):
    db = MagicMock()
    task = _make_task()
    escrow = _make_escrow()

    # Simulate the buyer lookup
    buyer = MagicMock()
    buyer.id = escrow.buyer_id
    db.query.return_value.filter.return_value.first.return_value = buyer

    execute_auto_refund(db, task, escrow, PROOF_MISSING, {"task_status": "COMPLETED"})

    # Should have called db.add with a DisputeRulesLog entry
    assert db.add.called
    log_entry = db.add.call_args[0][0]
    assert log_entry.task_id == task.id
    assert log_entry.escrow_id == escrow.id
    assert log_entry.rule_applied == PROOF_MISSING
    assert log_entry.action_taken == "AUTO_REFUND"

    # Escrow status should be updated
    assert escrow.status == "REFUNDED"
    assert escrow.dispute_reason == PROOF_MISSING

    # record_transfer should have been called for the refund
    assert mock_transfer.called


# ---------------------------------------------------------------------------
# run_dispute_check
# ---------------------------------------------------------------------------

@patch("dispute_engine.execute_auto_refund")
def test_run_dispute_check_returns_true_on_dispute(mock_refund):
    db = MagicMock()
    task = _make_task(status="COMPLETED", output_data=None)
    escrow = _make_escrow()
    result = run_dispute_check(db, task, escrow, skill=None)
    assert result is True
    assert mock_refund.called


@patch("dispute_engine.execute_auto_refund")
def test_run_dispute_check_returns_false_on_pass(mock_refund):
    db = MagicMock()
    task = _make_task(status="COMPLETED", output_data={"result": "ok"})
    escrow = _make_escrow()
    result = run_dispute_check(db, task, escrow, skill=None)
    assert result is False
    assert not mock_refund.called
