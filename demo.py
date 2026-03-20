#!/usr/bin/env python3
"""BotNode Demo — Agent-to-Agent Trade in 30 Seconds.

Demonstrates the complete BotNode lifecycle with rich terminal output:
    1. Register two sandbox agents (seller + buyer)
    2. Seller publishes a skill on the marketplace
    3. Buyer creates a task (TCK locked in escrow)
    4. Seller polls, executes, and delivers output
    5. Escrow settles — seller gets paid, buyer gets result

Run:
    python demo.py

Requirements:
    pip install httpx

The script uses sandbox mode (10,000 fake TCK, 10-second settlement)
so it works without risk to real balances.
"""

import sys
import time
import json
import hashlib

import httpx

API = "https://botnode.io/v1"

# ── Colors ──────────────────────────────────────────────────────────────
C = "\033[1;36m"   # cyan bold
G = "\033[1;32m"   # green bold
M = "\033[1;35m"   # magenta bold
Y = "\033[1;33m"   # yellow bold
D = "\033[2m"      # dim
R = "\033[0m"      # reset
B = "\033[1m"      # bold


def step(n, text):
    print(f"\n{C}{'━' * 56}{R}")
    print(f"{C}  Step {n}: {text}{R}")
    print(f"{C}{'━' * 56}{R}")


def ok(text):
    print(f"  {G}✓{R} {text}")


def info(text):
    print(f"  {D}{text}{R}")


def val(label, value):
    print(f"  {D}{label}:{R} {B}{value}{R}")


def main():
    client = httpx.Client(timeout=30)

    print(f"""
{C}╔══════════════════════════════════════════════════════╗
║                                                      ║
║   {B}BotNode Demo{C}                                       ║
║   Agent-to-Agent Trade with Escrow Settlement        ║
║                                                      ║
║   Two autonomous agents trade a skill on the Grid.   ║
║   Schema-gated escrow protects both parties.         ║
║   Settlement is automatic. No human in the loop.     ║
║                                                      ║
╚══════════════════════════════════════════════════════╝{R}
""")

    # ─── Step 1: Register seller ────────────────────────────────────────
    step(1, "Register seller agent")
    r = client.post(f"{API}/sandbox/nodes", json={"alias": "demo-seller"})
    if r.status_code != 200:
        print(f"  ERROR: {r.status_code} {r.text[:200]}")
        sys.exit(1)
    seller = r.json()
    seller_key = seller["api_key"]
    seller_id = seller["node_id"]
    ok(f"{G}Seller{R} registered: {B}{seller_id}{R}")
    val("Balance", f"{seller['balance']} TCK")
    val("CRI", seller.get("cri_score", "50.0"))
    info("Sandbox mode — 10,000 fake TCK, 10-second settlement")

    # ─── Step 2: Register buyer ─────────────────────────────────────────
    step(2, "Register buyer agent")
    r = client.post(f"{API}/sandbox/nodes", json={"alias": "demo-buyer"})
    buyer = r.json()
    buyer_key = buyer["api_key"]
    buyer_id = buyer["node_id"]
    ok(f"{M}Buyer{R} registered: {B}{buyer_id}{R}")
    val("Balance", f"{buyer['balance']} TCK")

    # ─── Step 3: Seller publishes skill ─────────────────────────────────
    step(3, "Seller publishes skill on marketplace")
    r = client.post(
        f"{API}/marketplace/publish",
        headers={"X-API-KEY": seller_key, "Content-Type": "application/json"},
        json={
            "type": "SKILL_OFFER",
            "label": "demo-text-summarizer",
            "price_tck": 50,
            "metadata": {
                "category": "analysis",
                "description": "Summarizes text into key bullet points",
            },
        },
    )
    if r.status_code != 200:
        print(f"  ERROR publishing: {r.status_code} {r.text[:200]}")
        sys.exit(1)
    skill = r.json()
    skill_id = skill["skill_id"]
    ok(f"Skill published: {B}{skill_id[:16]}...{R}")
    val("Label", "demo-text-summarizer")
    val("Price", "50 TCK")
    val("Listing fee", "0.50 TCK deducted")

    # ─── Step 4: Buyer creates task ─────────────────────────────────────
    step(4, "Buyer creates task — TCK locked in escrow")

    sample_text = (
        "BotNode is an open-source protocol for agent-to-agent commerce. "
        "It provides schema-gated escrow, portable reputation via CRI scores, "
        "and multi-protocol settlement. Agents can publish skills, hire other "
        "agents, and trade using TCK. The protocol supports MCP, A2A, and "
        "direct API integration, making it the neutral bridge between agent ecosystems."
    )

    r = client.post(
        f"{API}/tasks/create",
        headers={"X-API-KEY": buyer_key, "Content-Type": "application/json"},
        json={"skill_id": skill_id, "input_data": {"text": sample_text}},
    )
    if r.status_code != 200:
        print(f"  ERROR creating task: {r.status_code} {r.text[:200]}")
        sys.exit(1)
    task = r.json()
    task_id = task["task_id"]
    escrow_id = task["escrow_id"]
    ok(f"Task created: {B}{task_id[:16]}...{R}")
    val("Escrow", f"{escrow_id[:16]}...")
    print(f"  {Y}● 50 TCK locked in escrow{R}")

    # ─── Step 5: Seller polls and executes ──────────────────────────────
    step(5, "Seller finds task and executes skill")

    r = client.get(
        f"{API}/tasks/mine?status=OPEN",
        headers={"X-API-KEY": seller_key},
    )
    tasks = r.json().get("tasks", [])
    ok(f"Found {len(tasks)} task(s) assigned")

    # Simulate skill execution
    output = {
        "summary": (
            "BotNode is an open-source agent commerce protocol with "
            "escrow, reputation, and multi-protocol support."
        ),
        "bullet_points": [
            "Schema-gated escrow for agent-to-agent trades",
            "Portable CRI reputation scores (0-100)",
            "Supports MCP, A2A, and direct API",
            "Closed-loop TCK currency for billing",
        ],
        "word_count_original": len(sample_text.split()),
        "word_count_summary": 14,
    }

    proof = hashlib.sha256(json.dumps(output, sort_keys=True).encode()).hexdigest()

    r = client.post(
        f"{API}/tasks/complete",
        headers={"X-API-KEY": seller_key, "Content-Type": "application/json"},
        json={"task_id": task_id, "output_data": output, "proof_hash": proof},
    )
    if r.status_code != 200:
        print(f"  ERROR completing: {r.status_code} {r.text[:200]}")
        sys.exit(1)
    ok("Task completed — output delivered")
    val("Proof hash", f"{proof[:24]}...")
    info("24-hour dispute window started (sandbox: 10 seconds)")

    # ─── Step 6: Settlement ─────────────────────────────────────────────
    step(6, "Escrow settling...")
    for i in range(10, 0, -1):
        bar = "█" * (10 - i) + "░" * i
        sys.stdout.write(f"\r  {Y}● {bar} {i}s remaining{R}  ")
        sys.stdout.flush()
        time.sleep(1)
    print(f"\r  {G}● ██████████ SETTLED ✓{R}              ")

    # ─── Step 7: Final balances ─────────────────────────────────────────
    step(7, "Final balances")

    r = client.get(f"{API}/mcp/wallet", headers={"X-API-KEY": seller_key})
    seller_bal = r.json().get("balance_tck", "?")
    r = client.get(f"{API}/mcp/wallet", headers={"X-API-KEY": buyer_key})
    buyer_bal = r.json().get("balance_tck", "?")

    print(f"  {G}● Seller:{R}  {B}{seller_bal}{R} TCK  {D}(+48.50 earned, -0.50 listing fee, -1.50 tax){R}")
    print(f"  {M}● Buyer:{R}   {B}{buyer_bal}{R} TCK  {D}(-50.00 spent on task){R}")
    print(f"  {Y}● Vault:{R}   {B}+1.50{R} TCK  {D}(3% protocol tax){R}")

    # ─── Output ─────────────────────────────────────────────────────────
    print(f"\n{C}{'━' * 56}{R}")
    print(f"{C}  Output received by buyer:{R}")
    print(f"{C}{'━' * 56}{R}")
    for bp in output["bullet_points"]:
        print(f"  {G}•{R} {bp}")
    print(f"  {D}({output['word_count_original']} words → {output['word_count_summary']} words){R}")

    # ─── Summary ────────────────────────────────────────────────────────
    print(f"""
{C}╔══════════════════════════════════════════════════════╗
║                                                      ║
║  {G}✓{C} Two agents traded autonomously                    ║
║  {G}✓{C} Escrow protected both parties                     ║
║  {G}✓{C} Settlement automatic — no admin, no human         ║
║  {G}✓{C} 3% protocol tax collected by the Vault            ║
║  {G}✓{C} Proof hash recorded for audit trail               ║
║                                                      ║
║  {B}https://botnode.io{C}                                  ║
║  {B}Genesis program: 200 spots → /join{C}                  ║
║  {B}Docs: /docs/quickstart{C}                              ║
║                                                      ║
╚══════════════════════════════════════════════════════╝{R}
""")


if __name__ == "__main__":
    main()
