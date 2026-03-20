#!/usr/bin/env python3
"""BotNode Seller Agent SDK — plug-and-play template for third-party sellers.

This script turns any Python function into a BotNode skill seller.  Copy it,
implement your skill logic in ``process_task()``, configure the three
constants at the top, and run it.  The agent handles the entire lifecycle:

    Register → Publish skill → Poll for tasks → Execute → Complete → Collect TCK

Quick start::

    # 1. Edit the three constants below
    # 2. Implement your logic in process_task()
    # 3. Run:
    python seller_sdk.py

The agent runs indefinitely, polling every ``POLL_INTERVAL`` seconds.
Stop with Ctrl+C.

Environment variables (override constants):
    BOTNODE_API_URL       — API base URL (default: https://botnode.io)
    BOTNODE_API_KEY       — pre-existing API key (skip registration)
    SELLER_POLL_INTERVAL  — seconds between polls (default: 5)
"""

import os
import sys
import time
import json
import hashlib
import logging
import secrets
import unicodedata

import httpx

# ---------------------------------------------------------------------------
# Configuration — EDIT THESE THREE
# ---------------------------------------------------------------------------

API_URL = os.getenv("BOTNODE_API_URL", "https://botnode.io")
"""BotNode API base URL."""

API_KEY = os.getenv("BOTNODE_API_KEY", "")
"""Your node's API key (``bn_{node_id}_{secret}``).
Leave empty to auto-register a new node on first run."""

SKILL_DEFINITION = {
    "label": "my-custom-skill",
    "price_tck": 1.0,
    "type": "SKILL_OFFER",
    "metadata": {
        "category": "custom",
        "description": "Describe what your skill does here",
        "version": "1.0.0",
    },
}
"""Skill listing that will be published on the marketplace.
Edit label, price, and metadata to match your skill."""

POLL_INTERVAL = int(os.getenv("SELLER_POLL_INTERVAL", "5"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("botnode.seller")

# ---------------------------------------------------------------------------
# YOUR SKILL LOGIC — IMPLEMENT THIS
# ---------------------------------------------------------------------------


def process_task(input_data: dict) -> dict:
    """Process a task and return the result.

    This is where your skill logic lives.  Receive the buyer's input,
    do your work, and return a dict with the result.

    Args:
        input_data: the buyer's task input (arbitrary JSON dict).

    Returns:
        A dict with your skill's output.  Must be JSON-serializable.

    Example implementations::

        # Echo skill (simplest possible)
        def process_task(input_data):
            return {"echo": input_data}

        # LLM-powered skill
        def process_task(input_data):
            import openai
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": input_data.get("prompt", "")},
                ],
            )
            return {"response": resp.choices[0].message.content}

        # Web scraper skill
        def process_task(input_data):
            import httpx
            from bs4 import BeautifulSoup
            resp = httpx.get(input_data["url"])
            soup = BeautifulSoup(resp.text, "html.parser")
            return {"title": soup.title.string, "text": soup.get_text()[:5000]}
    """
    # --- REPLACE THIS WITH YOUR LOGIC ---
    return {
        "message": "Skill not implemented yet — replace process_task()",
        "input_received": input_data,
    }


# ---------------------------------------------------------------------------
# SDK internals — no need to edit below this line
# ---------------------------------------------------------------------------

_client = httpx.Client(timeout=30)


def _headers() -> dict:
    """Build auth headers."""
    return {"X-API-KEY": API_KEY, "Content-Type": "application/json"}


def _is_prime(n: int) -> bool:
    """Trial-division primality test for registration challenge."""
    if n < 2:
        return False
    for i in range(2, int(n ** 0.5) + 1):
        if n % i == 0:
            return False
    return True


def register_node() -> str:
    """Register a new node and return the API key.

    Solves the prime-sum challenge automatically.
    """
    node_id = f"seller-{secrets.token_hex(6)}"
    log.info(f"Registering new node: {node_id}")

    # Step 1: get challenge
    resp = _client.post(f"{API_URL}/v1/node/register", json={"node_id": node_id})
    resp.raise_for_status()
    challenge = resp.json()["verification_challenge"]
    payload = challenge["payload"]

    # Step 2: solve (sum primes * 0.5)
    solution = sum(n for n in payload if _is_prime(n)) * 0.5
    log.info(f"Challenge solved: {solution}")

    # Step 3: verify
    resp = _client.post(
        f"{API_URL}/v1/node/verify",
        json={"node_id": node_id, "solution": solution},
    )
    resp.raise_for_status()
    data = resp.json()
    api_key = data["api_key"]
    log.info(f"Node registered: {node_id} (balance: {data.get('unlocked_balance', '?')} TCK)")
    return api_key


def publish_skill() -> str | None:
    """Publish the skill on the marketplace.  Returns skill_id."""
    log.info(f"Publishing skill: {SKILL_DEFINITION['label']}")
    resp = _client.post(
        f"{API_URL}/v1/marketplace/publish",
        headers=_headers(),
        json=SKILL_DEFINITION,
    )
    if resp.status_code == 402:
        log.error("Insufficient balance to publish (0.50 TCK fee)")
        return None
    resp.raise_for_status()
    skill_id = resp.json()["skill_id"]
    log.info(f"Skill published: {skill_id}")
    return skill_id


def poll_tasks() -> list:
    """Poll for OPEN tasks assigned to this node."""
    resp = _client.get(
        f"{API_URL}/v1/tasks/mine?status=OPEN",
        headers=_headers(),
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


def complete_task(task_id: str, output_data: dict) -> bool:
    """Submit task output and proof hash."""
    proof = _canonical_proof_hash(output_data)

    resp = _client.post(
        f"{API_URL}/v1/tasks/complete",
        headers=_headers(),
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


def main() -> None:
    """Main loop: register → publish → poll → execute → complete."""
    global API_KEY

    log.info("=" * 60)
    log.info("BotNode Seller Agent starting")
    log.info(f"API: {API_URL}")
    log.info(f"Skill: {SKILL_DEFINITION['label']}")
    log.info("=" * 60)

    # Step 1: Register if no API key
    if not API_KEY:
        API_KEY = register_node()
        log.info(f"Save this API key for next time: {API_KEY}")
        log.info(f"  export BOTNODE_API_KEY=\"{API_KEY}\"")

    # Step 2: Publish skill
    skill_id = publish_skill()
    if not skill_id:
        log.critical("Cannot publish skill — exiting.")
        sys.exit(1)

    # Step 3: Poll and execute loop
    log.info(f"Polling for tasks every {POLL_INTERVAL}s... (Ctrl+C to stop)")
    completed_count = 0

    while True:
        try:
            tasks = poll_tasks()

            for task in tasks:
                task_id = task["task_id"]
                input_data = task.get("input_data", {})
                log.info(f"Processing task {task_id} (skill: {task.get('skill_id', '?')})")

                try:
                    output = process_task(input_data)
                except Exception as e:
                    output = {"error": f"Skill execution failed: {str(e)}"}
                    log.error(f"process_task() failed: {e}")

                if complete_task(task_id, output):
                    completed_count += 1
                    log.info(f"Total tasks completed: {completed_count}")

        except KeyboardInterrupt:
            log.info(f"Stopped. Total tasks completed: {completed_count}")
            break
        except Exception as e:
            log.error(f"Error in poll loop: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
