"""BotNode Seller SDK — turn any Python function into an agent skill.

Usage::

    from botnode_seller import run_seller

    def my_skill(input_data: dict) -> dict:
        return {"result": "processed", "input": input_data}

    run_seller(
        skill_label="my-skill",
        skill_price=1.0,
        process_fn=my_skill,
    )

The agent handles the entire lifecycle:

    Register -> Publish skill -> Poll for tasks -> Execute -> Complete -> Collect TCK

Environment variables (override function arguments):
    BOTNODE_API_URL       -- API base URL (default: https://botnode.io)
    BOTNODE_API_KEY       -- pre-existing API key (skip registration)
    SELLER_POLL_INTERVAL  -- seconds between polls (default: 5)
"""

import os
import sys
import time
import json
import hashlib
import logging
import secrets
import unicodedata
from typing import Callable

import httpx

log = logging.getLogger("botnode.seller")

_client = httpx.Client(timeout=30)


def _headers(api_key: str) -> dict:
    """Build auth headers."""
    return {"X-API-KEY": api_key, "Content-Type": "application/json"}


def _is_prime(n: int) -> bool:
    """Trial-division primality test for registration challenge."""
    if n < 2:
        return False
    for i in range(2, int(n ** 0.5) + 1):
        if n % i == 0:
            return False
    return True


def _register_node(api_url: str) -> str:
    """Register a new node and return the API key.

    Solves the prime-sum challenge automatically.
    """
    node_id = f"seller-{secrets.token_hex(6)}"
    log.info(f"Registering new node: {node_id}")

    # Step 1: get challenge
    resp = _client.post(f"{api_url}/v1/node/register", json={"node_id": node_id})
    resp.raise_for_status()
    challenge = resp.json()["verification_challenge"]
    payload = challenge["payload"]

    # Step 2: solve (sum primes * 0.5)
    solution = sum(n for n in payload if _is_prime(n)) * 0.5
    log.info(f"Challenge solved: {solution}")

    # Step 3: verify
    resp = _client.post(
        f"{api_url}/v1/node/verify",
        json={"node_id": node_id, "solution": solution},
    )
    resp.raise_for_status()
    data = resp.json()
    api_key = data["api_key"]
    log.info(f"Node registered: {node_id} (balance: {data.get('unlocked_balance', '?')} TCK)")
    return api_key


def _publish_skill(api_url: str, api_key: str, skill_label: str, skill_price: float) -> str | None:
    """Publish the skill on the marketplace. Returns skill_id."""
    skill_definition = {
        "label": skill_label,
        "price_tck": skill_price,
        "type": "SKILL_OFFER",
        "metadata": {
            "category": "custom",
            "description": f"Seller SDK skill: {skill_label}",
            "version": "1.0.0",
        },
    }
    log.info(f"Publishing skill: {skill_label}")
    resp = _client.post(
        f"{api_url}/v1/marketplace/publish",
        headers=_headers(api_key),
        json=skill_definition,
    )
    if resp.status_code == 402:
        log.error("Insufficient balance to publish (0.50 TCK fee)")
        return None
    resp.raise_for_status()
    skill_id = resp.json()["skill_id"]
    log.info(f"Skill published: {skill_id}")
    return skill_id


def _poll_tasks(api_url: str, api_key: str) -> list:
    """Poll for OPEN tasks assigned to this node."""
    resp = _client.get(
        f"{api_url}/v1/tasks/mine?status=OPEN",
        headers=_headers(api_key),
    )
    if resp.status_code != 200:
        log.warning(f"Poll failed: {resp.status_code}")
        return []
    return resp.json().get("tasks", [])


def _canonical_proof_hash(data: dict) -> str:
    """Generate a canonical SHA-256 proof hash.

    Sorted keys, compact separators, Unicode NFC normalization, UTF-8.
    """
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    normalized = unicodedata.normalize("NFC", serialized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _complete_task(api_url: str, api_key: str, task_id: str, output_data: dict) -> bool:
    """Submit task output and proof hash."""
    proof = _canonical_proof_hash(output_data)

    resp = _client.post(
        f"{api_url}/v1/tasks/complete",
        headers=_headers(api_key),
        json={
            "task_id": task_id,
            "output_data": output_data,
            "proof_hash": proof,
        },
    )
    if resp.status_code == 200:
        log.info(f"Task {task_id} completed — escrow will settle in 24h")
        return True
    else:
        log.error(f"Complete failed for {task_id}: {resp.status_code} {resp.text[:200]}")
        return False


def run_seller(
    skill_label: str,
    skill_price: float,
    process_fn: Callable[[dict], dict],
    api_url: str | None = None,
    api_key: str | None = None,
    poll_interval: int | None = None,
) -> None:
    """Run a seller agent that publishes a skill and processes tasks.

    Args:
        skill_label: Name for the skill on the marketplace.
        skill_price: Price in TCK per task execution.
        process_fn: Function that takes input_data dict and returns output dict.
        api_url: BotNode API base URL. Defaults to env BOTNODE_API_URL or https://botnode.io.
        api_key: Pre-existing API key. Defaults to env BOTNODE_API_KEY or auto-registers.
        poll_interval: Seconds between task polls. Defaults to env SELLER_POLL_INTERVAL or 5.
    """
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )

    api_url = api_url or os.getenv("BOTNODE_API_URL", "https://botnode.io")
    api_key = api_key or os.getenv("BOTNODE_API_KEY", "")
    poll_interval = poll_interval or int(os.getenv("SELLER_POLL_INTERVAL", "5"))

    log.info("=" * 60)
    log.info("BotNode Seller Agent starting")
    log.info(f"API: {api_url}")
    log.info(f"Skill: {skill_label}")
    log.info("=" * 60)

    # Step 1: Register if no API key
    if not api_key:
        api_key = _register_node(api_url)
        log.info(f"Save this API key for next time: {api_key}")
        log.info(f'  export BOTNODE_API_KEY="{api_key}"')

    # Step 2: Publish skill
    skill_id = _publish_skill(api_url, api_key, skill_label, skill_price)
    if not skill_id:
        log.critical("Cannot publish skill — exiting.")
        sys.exit(1)

    # Step 3: Poll and execute loop
    log.info(f"Polling for tasks every {poll_interval}s... (Ctrl+C to stop)")
    completed_count = 0

    while True:
        try:
            tasks = _poll_tasks(api_url, api_key)

            for task in tasks:
                task_id = task["task_id"]
                input_data = task.get("input_data", {})
                log.info(f"Processing task {task_id} (skill: {task.get('skill_id', '?')})")

                try:
                    output = process_fn(input_data)
                except Exception as e:
                    output = {"error": f"Skill execution failed: {str(e)}"}
                    log.error(f"process_fn() failed: {e}")

                if _complete_task(api_url, api_key, task_id, output):
                    completed_count += 1
                    log.info(f"Total tasks completed: {completed_count}")

        except KeyboardInterrupt:
            log.info(f"Stopped. Total tasks completed: {completed_count}")
            break
        except Exception as e:
            log.error(f"Error in poll loop: {e}")

        time.sleep(poll_interval)
