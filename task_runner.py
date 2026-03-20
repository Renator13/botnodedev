"""Task Runner — polls OPEN tasks for house skills and executes them.

This is the bridge between the escrow/task system and the skill containers.
It runs as a standalone process alongside the API server:

    python task_runner.py

Flow for each iteration:
1. Query all OPEN tasks where ``seller_id == HOUSE_NODE_ID``
2. Claim the task (mark IN_PROGRESS to prevent duplicate execution)
3. POST the task's ``input_data`` to MUTHUR's ``/run`` endpoint
4. Unwrap MUTHUR response (extract result from wrapper)
5. Call the API's ``/v1/tasks/complete`` with the result
6. Wait before processing the next task (respect rate limits)

The runner authenticates as the house node using its API key.
All skills are routed through MUTHUR (``MUTHUR_URL``).

Environment variables:
    HOUSE_NODE_API_KEY   — API key for the botnode-official house node
    TASK_RUNNER_INTERVAL — seconds between poll cycles (default: 5)
    MUTHUR_URL           — MUTHUR gateway URL (default: http://localhost:8090)
    TASK_DELAY           — seconds between tasks in the same batch (default: 3)
    MAX_RETRIES          — max retries per task on MUTHUR failure (default: 3)
"""

import os
import sys
import time
import logging
import hashlib
import json

import httpx

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("botnode.task_runner")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
HOUSE_NODE_API_KEY = os.getenv("HOUSE_NODE_API_KEY", "")
POLL_INTERVAL = int(os.getenv("TASK_RUNNER_INTERVAL", "5"))
MUTHUR_URL = os.getenv("MUTHUR_URL", "http://localhost:8090")
TASK_DELAY = int(os.getenv("TASK_DELAY", "3"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))


def get_skill_endpoint(skill_id: str) -> str:
    """Return the MUTHUR /run URL. Always."""
    return f"{MUTHUR_URL}/run"


# Sandbox preview: tells the user what keys the real output would contain.
_SANDBOX_SAMPLE_KEYS = {
    "sentiment_analyzer_v1": ["sentiment", "confidence", "emotions"],
    "code_reviewer_v1": ["issues", "complexity", "suggestions"],
    "web_research_v1": ["research", "sources", "summary"],
    "hallucination_detector_v1": ["verdict", "confidence", "evidence"],
    "performance_analyzer_v1": ["issues", "complexity", "optimization_priority"],
    "prompt_optimizer_v1": ["optimized_prompt", "changes", "improvement_score"],
    "compliance_checker_v1": ["compliant", "violations", "recommendations"],
    "text_translator_v1": ["translated_text", "source_language", "target_language"],
    "document_reporter_v1": ["summary", "key_findings", "metrics"],
    "report_builder_v1": ["report", "sections", "charts"],
    "report_compiler_v1": ["compiled_report", "table_of_contents"],
    "schema_generator_v1": ["json_schema", "description"],
    "logic_visualizer_v1": ["diagram", "truth_table", "simplification"],
    "quality_gate_v1": ["passed", "overall_score", "criteria_results"],
    "scheduler_v1": ["schedule", "timeline", "dependencies"],
    "google_search_v1": ["search_results", "total_results"],
    "key_point_extractor_v1": ["key_points", "summary"],
    "language_detector_v1": ["language", "confidence", "alternatives"],
    "lead_enricher_v1": ["company_info", "contacts", "social"],
    "vector_memory_v1": ["stored", "key", "similarity"],
    "csv_parser_v1": ["headers", "rows", "row_count"],
    "pdf_parser_v1": ["text", "pages", "metadata"],
    "url_fetcher_v1": ["url", "status_code", "text"],
    "web_scraper_v1": ["title", "text", "links"],
    "diff_analyzer_v1": ["unified_diff", "similarity_ratio", "changes"],
    "image_describer_v1": ["width", "height", "format", "dominant_colors"],
    "text_to_voice_v1": ["audio_base64", "format", "duration"],
    "schema_enforcer_v1": ["valid", "errors", "error_count"],
    "notification_router_v1": ["delivered", "status_code"],
}


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------

def execute_single_task(task: dict, headers: dict) -> bool:
    """Execute a single task. Returns True if completed successfully."""
    task_id = task["task_id"]
    skill_id = task["skill_id"]
    skill_label = task.get("skill_label", skill_id)
    input_data = task.get("input_data", {})
    endpoint = get_skill_endpoint(skill_id)

    buyer_id = task.get("buyer_id", "")
    is_sandbox = buyer_id.startswith("sandbox-")

    logger.info(f"Processing task {task_id} ({skill_label}){' [SANDBOX]' if is_sandbox else ''}")

    # 1. Claim the task (mark IN_PROGRESS)
    try:
        claim_resp = httpx.post(
            f"{API_BASE}/v1/tasks/{task_id}/claim",
            headers=headers,
            timeout=5,
        )
        if claim_resp.status_code != 200:
            logger.warning(f"Cannot claim {task_id}: {claim_resp.status_code} — skipping")
            return False
    except Exception as e:
        logger.warning(f"Claim failed for {task_id}: {e} — skipping")
        return False

    # 2. Sandbox preview — skip MUTHUR, return registration prompt
    if is_sandbox:
        sample_keys = _SANDBOX_SAMPLE_KEYS.get(skill_label, ["result"])
        output_data = {
            "preview": True,
            "skill": skill_label,
            "status": "executed",
            "pipeline": "escrow_lock → claim → execute → settle (all real, zero mock)",
            "output_keys": sample_keys,
            "message": (
                f"That was real. Escrow locked, task claimed, settlement queued — "
                f"the full pipeline, not a simulation. "
                f"The only thing missing is the output: {', '.join(sample_keys)}. "
                f"Register a node, get 100 TCK on the house, and the next response comes back full."
            ),
            "next": "POST /v1/node/register — three fields, one API call, you're live.",
            "docs": "https://botnode.dev/docs/quickstart",
        }
        logger.info(f"Sandbox preview for {task_id} ({skill_label})")
        proof = hashlib.sha256(json.dumps(output_data, sort_keys=True).encode()).hexdigest()
        try:
            complete_resp = httpx.post(
                f"{API_BASE}/v1/tasks/complete",
                headers=headers,
                json={"task_id": task_id, "output_data": output_data, "proof_hash": proof},
                timeout=10,
            )
            if complete_resp.status_code == 200:
                logger.info(f"Sandbox task {task_id} completed (preview)")
                return True
            else:
                logger.error(f"Sandbox complete failed: {complete_resp.status_code} {complete_resp.text[:100]}")
                return False
        except Exception as e:
            logger.error(f"Sandbox complete error: {e}")
            return False

    # 3. Call MUTHUR with retry
    output_data = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            payload = {"skill_id": skill_label, "data": input_data, "input": input_data}
            logger.info(f"MUTHUR attempt {attempt}/{MAX_RETRIES} for {skill_label}")

            skill_resp = httpx.post(endpoint, json=payload, timeout=90)

            if skill_resp.status_code == 200:
                raw = skill_resp.json()

                # Unwrap MUTHUR response
                if isinstance(raw, dict) and "result" in raw:
                    muthur_ok = raw.get("ok", False)
                    muthur_error = raw.get("error")

                    if not muthur_ok or muthur_error:
                        logger.warning(f"MUTHUR error on attempt {attempt}: {muthur_error}")
                        if attempt < MAX_RETRIES:
                            wait = attempt * 5
                            logger.info(f"Waiting {wait}s before retry...")
                            time.sleep(wait)
                            continue
                        else:
                            logger.error(f"All {MAX_RETRIES} attempts failed for {task_id}")
                            return False

                    output_data = raw["result"]
                    logger.info(f"MUTHUR success: keys={list(output_data.keys()) if isinstance(output_data, dict) else type(output_data)}")
                    break
                else:
                    output_data = raw
                    break

            elif skill_resp.status_code == 429:
                # Rate limited — wait and retry
                wait = attempt * 10
                logger.warning(f"Rate limited (429) on attempt {attempt}. Waiting {wait}s...")
                time.sleep(wait)
                continue
            else:
                logger.error(f"MUTHUR returned {skill_resp.status_code}: {skill_resp.text[:200]}")
                if attempt < MAX_RETRIES:
                    time.sleep(attempt * 5)
                    continue
                return False

        except httpx.TimeoutException:
            logger.error(f"Timeout on attempt {attempt} for {task_id}")
            if attempt < MAX_RETRIES:
                time.sleep(attempt * 5)
                continue
            return False
        except Exception as e:
            logger.error(f"Exception on attempt {attempt}: {type(e).__name__}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(attempt * 3)
                continue
            return False

    if not output_data:
        logger.error(f"No output for {task_id} after {MAX_RETRIES} attempts — completing with error")
        output_data = {"error": f"Skill execution failed after {MAX_RETRIES} attempts"}

    # Check for error in output — still complete the task so escrow can refund
    if isinstance(output_data, dict) and output_data.get("error"):
        logger.warning(f"Skill returned error for {task_id}: {output_data['error']}")
        # Fall through to complete — the settlement worker will auto-refund error tasks

    # 3. Complete the task
    proof = hashlib.sha256(json.dumps(output_data, sort_keys=True).encode()).hexdigest()
    try:
        complete_resp = httpx.post(
            f"{API_BASE}/v1/tasks/complete",
            headers=headers,
            json={
                "task_id": task_id,
                "output_data": output_data,
                "proof_hash": proof,
            },
            timeout=10,
        )
        if complete_resp.status_code == 200:
            logger.info(f"Task {task_id} completed successfully")
            return True
        else:
            logger.error(f"Complete failed for {task_id}: {complete_resp.status_code} {complete_resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Error completing {task_id}: {e}")
        return False


def poll_and_execute() -> int:
    """Poll for OPEN tasks and execute them one by one with pacing."""
    if not HOUSE_NODE_API_KEY:
        logger.error("HOUSE_NODE_API_KEY not set")
        return 0

    headers = {"X-API-KEY": HOUSE_NODE_API_KEY}

    # Poll for OPEN tasks
    try:
        resp = httpx.get(
            f"{API_BASE}/v1/tasks/mine?status=OPEN",
            headers=headers,
            timeout=10,
        )
        if resp.status_code != 200:
            return 0
        tasks = resp.json().get("tasks", [])
    except Exception as e:
        logger.error(f"Poll error: {e}")
        return 0

    if not tasks:
        return 0

    logger.info(f"Found {len(tasks)} OPEN task(s) — processing one by one")

    completed = 0
    for i, task in enumerate(tasks):
        success = execute_single_task(task, headers)
        if success:
            completed += 1

        # Pace between tasks to respect MUTHUR rate limits
        if i < len(tasks) - 1:
            logger.info(f"Pacing: waiting {TASK_DELAY}s before next task...")
            time.sleep(TASK_DELAY)

    return completed


def main() -> None:
    """Run the task runner loop."""
    logger.info(f"Task Runner starting (poll={POLL_INTERVAL}s, delay={TASK_DELAY}s, retries={MAX_RETRIES}, MUTHUR={MUTHUR_URL})")

    if not HOUSE_NODE_API_KEY:
        logger.critical("HOUSE_NODE_API_KEY is required. Set it in .env and restart.")
        sys.exit(1)

    while True:
        try:
            completed = poll_and_execute()
            if completed:
                logger.info(f"Cycle: {completed} task(s) completed")
        except KeyboardInterrupt:
            logger.info("Stopped by user")
            break
        except Exception as e:
            logger.error(f"Main loop error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
