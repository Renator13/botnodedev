"""Task Runner — polls OPEN tasks for house skills and executes them.

This is the bridge between the escrow/task system and the skill containers.
It runs as a standalone process alongside the API server:

    python task_runner.py

Flow for each iteration:
1. Query all OPEN tasks where ``seller_id == HOUSE_NODE_ID``
2. For each task, look up the skill container endpoint
3. POST the task's ``input_data`` to the container's ``/run`` endpoint
4. Call the API's ``/v1/tasks/complete`` with the result
5. Sleep and repeat

The runner authenticates as the house node using its API key.  Skill
all skills are routed through MUTHUR (``MUTHUR_URL``).

Environment variables:
    HOUSE_NODE_API_KEY   — API key for the botnode-official house node
    TASK_RUNNER_INTERVAL — seconds between poll cycles (default: 5)
    SKILL_BASE_URL       — override base URL for skill containers
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


def get_skill_endpoint(skill_id: str) -> str:
    """Return the MUTHUR /run URL.  Always.

    MUTHUR is the single point of entry for ALL skills — it decides
    whether to proxy to a container or call an LLM.  The Task Runner
    doesn't need to know the difference.
    """
    return f"{MUTHUR_URL}/run"


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------

def poll_and_execute() -> int:
    """Poll for OPEN tasks assigned to the house node and execute them.

    Returns the number of tasks successfully completed this cycle.
    """
    if not HOUSE_NODE_API_KEY:
        logger.error("HOUSE_NODE_API_KEY not set — cannot authenticate as house node")
        return 0

    headers = {"X-API-KEY": HOUSE_NODE_API_KEY}
    completed = 0

    # 1. Poll for OPEN tasks
    try:
        resp = httpx.get(
            f"{API_BASE}/v1/tasks/mine?status=OPEN",
            headers=headers,
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(f"Poll failed: {resp.status_code} {resp.text[:200]}")
            return 0
        tasks = resp.json().get("tasks", [])
    except Exception as e:
        logger.error(f"Poll error: {e}")
        return 0

    if not tasks:
        return 0

    logger.info(f"Found {len(tasks)} OPEN task(s)")

    # 2. Execute each task
    for task in tasks:
        task_id = task["task_id"]
        skill_id = task["skill_id"]
        input_data = task.get("input_data", {})

        endpoint = get_skill_endpoint(skill_id)
        if not endpoint:
            logger.warning(f"No endpoint for skill {skill_id} — skipping task {task_id}")
            continue

        logger.info(f"Executing task {task_id} via {endpoint}")

        # 3. Call MUTHUR (routes to container or LLM internally)
        try:
            payload = {"skill_id": skill_id, "data": input_data, "input": input_data}
            skill_resp = httpx.post(
                endpoint,
                json=payload,
                timeout=60,
            )
            if skill_resp.status_code == 200:
                output_data = skill_resp.json()
            else:
                output_data = {
                    "error": f"Skill returned {skill_resp.status_code}",
                    "details": skill_resp.text[:500],
                }
        except httpx.TimeoutException:
            output_data = {"error": "Skill execution timed out"}
            logger.error(f"Timeout executing skill {skill_id} for task {task_id}")
        except Exception as e:
            output_data = {"error": f"Skill execution failed: {str(e)}"}
            logger.error(f"Error executing skill {skill_id}: {e}")

        # 4. Check if skill succeeded — only complete on success
        is_success = output_data.get("ok", True) if isinstance(output_data, dict) else True
        has_error = "error" in output_data if isinstance(output_data, dict) else False

        if has_error and not is_success:
            # Skill failed — leave task OPEN, escrow auto-refunds after 72h
            logger.warning(f"Task {task_id} skill failed: {output_data.get('error', '?')} — leaving OPEN for auto-refund")
            continue

        # 5. Complete the task via API
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
                completed += 1
            else:
                logger.error(f"Complete failed for {task_id}: {complete_resp.status_code} {complete_resp.text[:200]}")
        except Exception as e:
            logger.error(f"Error completing task {task_id}: {e}")

    return completed


def main() -> None:
    """Run the task runner loop."""
    logger.info(f"Task Runner starting (poll interval: {POLL_INTERVAL}s, API: {API_BASE})")

    if not HOUSE_NODE_API_KEY:
        logger.critical("HOUSE_NODE_API_KEY is required. Set it in .env and restart.")
        sys.exit(1)

    while True:
        try:
            completed = poll_and_execute()
            if completed:
                logger.info(f"Cycle complete: {completed} task(s) executed")
        except KeyboardInterrupt:
            logger.info("Task Runner stopped by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
