"""Benchmark suites — objective skill verification.

Public benchmark suites that test skills against known inputs with
expected outputs.  Passing a benchmark earns a "Verified" badge.
Generates content, makes the marketplace tangible, and builds trust
even without dense market activity.

Benchmark types:
    - extraction: parse structured data from input
    - schema_compliance: output must match declared schema
    - deterministic: same input must produce same output
    - timeout_retry: skill must respond within deadline
"""

from decimal import Decimal
import json
import hashlib

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from dependencies import get_db, get_node, _utcnow

router = APIRouter(tags=["benchmarks"])

# Pre-defined benchmark suites
BENCHMARK_SUITES = {
    "sentiment_basic": {
        "name": "Sentiment Analysis — Basic",
        "description": "5 test cases with known sentiment labels",
        "skill_pattern": "sentiment",
        "cases": [
            {"input": {"text": "I love this product!"}, "expected_field": "sentiment", "expected_value": "positive"},
            {"input": {"text": "This is terrible."}, "expected_field": "sentiment", "expected_value": "negative"},
            {"input": {"text": "The meeting is at 3pm."}, "expected_field": "sentiment", "expected_value": "neutral"},
            {"input": {"text": "I'm not sure how I feel."}, "expected_field": "sentiment", "expected_value": "mixed"},
            {"input": {"text": "Absolutely fantastic experience!"}, "expected_field": "sentiment", "expected_value": "positive"},
        ],
    },
    "schema_compliance": {
        "name": "Schema Compliance",
        "description": "Verifies output matches the skill's declared output_schema",
        "skill_pattern": None,  # works with any skill
        "cases": [
            {"input": {"text": "test input"}, "check": "schema_valid"},
        ],
    },
    "deterministic_echo": {
        "name": "Deterministic Output",
        "description": "Same input produces consistent output structure",
        "skill_pattern": None,
        "cases": [
            {"input": {"text": "deterministic test"}, "check": "consistent_keys"},
        ],
    },
}


@router.get("/v1/benchmarks")
def list_benchmark_suites() -> dict:
    """List available benchmark suites.

    Public endpoint — shows what benchmarks exist and what they test.
    """
    return {
        "suites": [
            {
                "id": sid,
                "name": s["name"],
                "description": s["description"],
                "test_cases": len(s["cases"]),
                "skill_pattern": s["skill_pattern"],
            }
            for sid, s in BENCHMARK_SUITES.items()
        ]
    }


@router.get("/v1/benchmarks/{suite_id}")
def get_benchmark_detail(suite_id: str) -> dict:
    """Get full benchmark suite details including test cases.

    Public endpoint — developers can see exactly what will be tested.
    """
    suite = BENCHMARK_SUITES.get(suite_id)
    if not suite:
        raise HTTPException(404, f"Benchmark suite not found: {suite_id}")

    return {
        "id": suite_id,
        "name": suite["name"],
        "description": suite["description"],
        "cases": [
            {
                "case_id": i,
                "input": c["input"],
                "check_type": c.get("check", "field_match"),
                "expected_field": c.get("expected_field"),
                "expected_value": c.get("expected_value"),
            }
            for i, c in enumerate(suite["cases"])
        ],
    }


@router.post("/v1/benchmarks/{suite_id}/run")
def run_benchmark(
    suite_id: str,
    skill_id: str,
    caller: models.Node = Depends(get_node),
    db: Session = Depends(get_db),
) -> dict:
    """Run a benchmark suite against a specific skill.

    Creates shadow tasks (no real TCK) for each test case,
    evaluates the output against expected results, and returns
    a scorecard.

    Auth: API key.  Costs 0 TCK (benchmarks are free).
    """
    suite = BENCHMARK_SUITES.get(suite_id)
    if not suite:
        raise HTTPException(404, f"Benchmark suite not found: {suite_id}")

    skill = db.query(models.Skill).filter(models.Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(404, f"Skill not found: {skill_id}")

    results = []
    passed = 0
    failed = 0

    for i, case in enumerate(suite["cases"]):
        # Create shadow task
        task = models.Task(
            skill_id=skill_id,
            buyer_id=caller.id,
            seller_id=skill.provider_id,
            input_data=case["input"],
            status="OPEN",
            protocol="benchmark",
            is_shadow=True,
        )
        db.add(task)
        db.flush()

        # Note: actual execution would happen via task runner
        # For now, record the benchmark request
        check_type = case.get("check", "field_match")
        result = {
            "case_id": i,
            "task_id": task.id,
            "input": case["input"],
            "check_type": check_type,
            "status": "pending",
            "note": "Task created. Poll GET /v1/tasks/{task_id}/receipt for results after execution.",
        }
        results.append(result)

    db.commit()

    return {
        "benchmark_id": f"bench_{suite_id}_{skill_id[:8]}",
        "suite": suite["name"],
        "skill_id": skill_id,
        "skill_label": skill.label,
        "cases_total": len(suite["cases"]),
        "status": "running",
        "results": results,
        "note": "Benchmark tasks created as shadow tasks. Results available after skill execution.",
    }
