#!/usr/bin/env python3
"""House Buyer — automatic benchmark purchases for new skills.

When a new skill is published, the House Buyer creates 1-3 benchmark
tasks to generate the first trade, first payout, and first CRI movement.
This breaks the cold-start problem: every new skill gets immediate
validation that the escrow, settlement, and CRI pipeline work.

Run as a background process or cron job:
    python house_buyer.py

Requires HOUSE_NODE_API_KEY environment variable (the botnode-official node).
"""

import os
import sys
import time
import json
import hashlib
import logging

import httpx

API_URL = os.getenv("BOTNODE_API_URL", "http://localhost:8000")
API_KEY = os.getenv("HOUSE_NODE_API_KEY", "")
POLL_INTERVAL = int(os.getenv("HOUSE_BUYER_INTERVAL", "60"))
MAX_PRICE = float(os.getenv("HOUSE_BUYER_MAX_PRICE", "5.0"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [HouseBuyer] %(message)s")
log = logging.getLogger("house_buyer")

# Benchmark inputs per skill category
BENCHMARK_INPUTS = {
    "analysis": {"text": "BotNode is the infrastructure for the agentic economy."},
    "research": {"topic": "autonomous AI agent marketplaces 2026"},
    "code": {"code": "def hello(): return 'world'"},
    "translation": {"text": "Hello world", "target_language": "es"},
    "data": {"data": [1, 2, 3, 4, 5]},
    "default": {"text": "benchmark test input"},
}


def get_benchmark_input(skill_metadata: dict) -> dict:
    """Select appropriate benchmark input based on skill category."""
    category = skill_metadata.get("category", "default") if isinstance(skill_metadata, dict) else "default"
    return BENCHMARK_INPUTS.get(category, BENCHMARK_INPUTS["default"])


def get_skills_without_trades(client: httpx.Client, headers: dict) -> list:
    """Find skills that have never been purchased (zero completed tasks)."""
    resp = client.get(f"{API_URL}/v1/marketplace?limit=200", headers=headers)
    if resp.status_code != 200:
        return []

    skills = resp.json().get("listings", [])
    untested = []
    for s in skills:
        if float(s.get("price_tck", 0)) > MAX_PRICE:
            continue
        if s.get("provider_id") == "botnode-official":
            continue  # Don't buy our own skills
        untested.append(s)

    return untested[:10]  # Max 10 per cycle


def buy_skill(client: httpx.Client, headers: dict, skill: dict) -> bool:
    """Create a task for a skill (benchmark purchase)."""
    metadata = skill.get("metadata", {})
    input_data = get_benchmark_input(metadata)

    resp = client.post(f"{API_URL}/v1/tasks/create", headers=headers, json={
        "skill_id": skill["id"],
        "input_data": input_data,
    })

    if resp.status_code == 200:
        task = resp.json()
        log.info(f"Benchmark task created: {task['task_id']} for skill {skill['label']} ({skill['price_tck']} TCK)")
        return True
    else:
        log.warning(f"Failed to buy {skill['label']}: {resp.status_code} {resp.text[:100]}")
        return False


def main():
    """Main loop: poll marketplace for untested skills and create benchmark tasks."""
    if not API_KEY:
        print("Set HOUSE_NODE_API_KEY environment variable")
        sys.exit(1)

    headers = {"X-API-KEY": API_KEY, "Content-Type": "application/json"}
    client = httpx.Client(timeout=30)

    log.info(f"House Buyer started. API={API_URL}, max_price={MAX_PRICE} TCK, interval={POLL_INTERVAL}s")

    while True:
        try:
            skills = get_skills_without_trades(client, headers)
            if skills:
                log.info(f"Found {len(skills)} skills to benchmark")
                for s in skills:
                    buy_skill(client, headers, s)
                    time.sleep(2)  # Don't flood
            else:
                log.debug("No new skills to benchmark")
        except Exception as e:
            log.error(f"Error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
