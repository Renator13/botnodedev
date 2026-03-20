"""Validator hooks — custom acceptance conditions for tasks.

Buyers can create validators and attach them to tasks. Before
settlement, each validator runs against the task output. If any
validator returns FAIL, the escrow is auto-refunded.

Validator types:
    - schema: JSON Schema validation (extends the built-in dispute engine)
    - regex: pattern match against output fields
    - webhook: call an external URL that returns PASS/FAIL

This addresses the #1 CTO objection: "JSON can validate and still be garbage."
"""

import json
import re
from typing import Optional

import httpx
import jsonschema
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from dependencies import get_db, get_node, get_current_node

router = APIRouter(tags=["validators"])


class ValidatorCreate(BaseModel):
    name: str = Field(..., max_length=100)
    type: str = Field(..., pattern=r"^(schema|regex|webhook)$")
    config: dict


@router.post("/v1/validators")
def create_validator(
    req: ValidatorCreate,
    node: models.Node = Depends(get_current_node),
    db: Session = Depends(get_db),
) -> dict:
    """Create a reusable validator.

    Validators can be attached to tasks at creation time via the
    ``validator_ids`` field.  Before settlement, each validator
    runs against the task output.
    """
    # Validate config based on type
    if req.type == "schema" and "schema" not in req.config:
        raise HTTPException(400, "Schema validators require a 'schema' key in config")
    if req.type == "regex" and "pattern" not in req.config:
        raise HTTPException(400, "Regex validators require a 'pattern' key in config")
    if req.type == "webhook":
        url = req.config.get("url", "")
        if not url.startswith("https://"):
            raise HTTPException(400, "Webhook validators require an HTTPS URL")

    existing = db.query(models.Validator).filter(
        models.Validator.node_id == node.id,
        models.Validator.active == True,
    ).count()
    if existing >= 20:
        raise HTTPException(400, "Maximum 20 validators per node")

    v = models.Validator(
        node_id=node.id,
        name=req.name,
        type=req.type,
        config=req.config,
    )
    db.add(v)
    db.commit()

    return {"validator_id": v.id, "name": v.name, "type": v.type}


@router.get("/v1/validators")
def list_validators(
    node: models.Node = Depends(get_current_node),
    db: Session = Depends(get_db),
) -> dict:
    """List your active validators."""
    vs = db.query(models.Validator).filter(
        models.Validator.node_id == node.id,
        models.Validator.active == True,
    ).all()
    return {
        "validators": [
            {"id": v.id, "name": v.name, "type": v.type, "config": v.config}
            for v in vs
        ]
    }


@router.get("/v1/tasks/{task_id}/validations")
def get_task_validations(
    task_id: str,
    caller: models.Node = Depends(get_node),
    db: Session = Depends(get_db),
) -> dict:
    """View validator results for a task."""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    if caller.id not in (task.buyer_id, task.seller_id):
        raise HTTPException(403, "Not a party to this task")

    results = db.query(models.ValidatorResult).filter(
        models.ValidatorResult.task_id == task_id,
    ).all()

    return {
        "task_id": task_id,
        "results": [
            {
                "validator_id": r.validator_id,
                "result": r.result,
                "details": r.details,
                "evaluated_at": r.evaluated_at.isoformat() if r.evaluated_at else None,
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Validator execution (called by the settlement pipeline)
# ---------------------------------------------------------------------------

def run_validators(db: Session, task: models.Task) -> tuple[bool, Optional[str]]:
    """Run all validators attached to a task.

    Returns (all_passed, failure_details).
    Called by the auto-settle flow before settlement.
    """
    if not task.validator_ids:
        return (True, None)

    validator_ids = task.validator_ids
    if isinstance(validator_ids, str):
        validator_ids = json.loads(validator_ids)

    output = task.output_data or {}

    for vid in validator_ids:
        v = db.query(models.Validator).filter(models.Validator.id == vid).first()
        if not v or not v.active:
            continue

        result, details = _evaluate_single(v, output)

        # Record result
        vr = models.ValidatorResult(
            task_id=task.id,
            validator_id=vid,
            result=result,
            details=details,
        )
        db.add(vr)

        if result == "FAIL":
            return (False, json.dumps({"validator_id": vid, "name": v.name, "details": details}))

    return (True, None)


def _evaluate_single(validator: models.Validator, output: dict) -> tuple[str, Optional[dict]]:
    """Evaluate a single validator against task output."""
    config = validator.config
    if isinstance(config, str):
        config = json.loads(config)

    try:
        if validator.type == "schema":
            return _eval_schema(config, output)
        elif validator.type == "regex":
            return _eval_regex(config, output)
        elif validator.type == "webhook":
            return _eval_webhook(config, output)
        else:
            return ("ERROR", {"error": f"Unknown type: {validator.type}"})
    except Exception as exc:
        return ("ERROR", {"exception": str(exc)[:200]})


def _eval_schema(config: dict, output: dict) -> tuple[str, Optional[dict]]:
    """Validate output against JSON Schema."""
    schema = config.get("schema")
    if not schema:
        return ("ERROR", {"error": "No schema in config"})
    try:
        jsonschema.validate(instance=output, schema=schema)
        return ("PASS", None)
    except jsonschema.ValidationError as exc:
        return ("FAIL", {"error": str(exc.message), "path": [str(p) for p in exc.absolute_path]})


def _eval_regex(config: dict, output: dict) -> tuple[str, Optional[dict]]:
    """Check that output (or a field) matches a regex pattern."""
    pattern = config.get("pattern", "")
    field = config.get("field")
    target = json.dumps(output) if not field else str(output.get(field, ""))
    if re.search(pattern, target):
        return ("PASS", None)
    return ("FAIL", {"pattern": pattern, "field": field, "matched": False})


def _eval_webhook(config: dict, output: dict) -> tuple[str, Optional[dict]]:
    """Call external validation endpoint."""
    url = config.get("url", "")
    if not url.startswith("https://"):
        return ("ERROR", {"error": "Invalid URL"})
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(url, json={"output": output})
            if resp.status_code != 200:
                return ("INCONCLUSIVE", {"http_status": resp.status_code})
            body = resp.json()
            result = body.get("result", "INCONCLUSIVE").upper()
            if result not in ("PASS", "FAIL", "INCONCLUSIVE"):
                result = "INCONCLUSIVE"
            return (result, body.get("details"))
    except Exception as exc:
        return ("INCONCLUSIVE", {"error": str(exc)[:200]})
