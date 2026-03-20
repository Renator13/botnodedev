#!/usr/bin/env python3
"""BotNode Demo — execute a full transaction cycle for storytelling.

Runs the complete flow with rich console output suitable for recording:
  1. Register buyer + seller nodes
  2. Seller publishes a skill
  3. Buyer purchases the skill (escrow + task)
  4. Task Runner executes the skill
  5. Escrow settles (fast-forwarded for demo)
  6. Both balances updated, ledger entries created

Usage:
    python bin/demo_transaction.py [--api http://localhost:8000]

Record with:
    asciinema rec demo.cast -c "python bin/demo_transaction.py"
"""

import argparse
import json
import time
import sys
import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PAUSE = 1.5  # seconds between steps (for readability in recording)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def p(label: str, data=None):
    """Pretty print a step."""
    print(f"\n{'─' * 60}")
    print(f"  {label}")
    print(f"{'─' * 60}")
    if data:
        print(json.dumps(data, indent=2, default=str))
    time.sleep(PAUSE)


def is_prime(n):
    if n < 2: return False
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0: return False
    return True


def register_node(client, base, node_id):
    """Register and verify a node, return API key."""
    reg = client.post(f"{base}/v1/node/register", json={"node_id": node_id}).json()
    payload = reg["verification_challenge"]["payload"]
    solution = sum(n for n in payload if is_prime(n)) * 0.5
    ver = client.post(f"{base}/v1/node/verify", json={
        "node_id": node_id, "solution": solution
    }).json()
    return ver["api_key"], ver


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="BotNode transaction demo")
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--admin-key", default="", help="Admin key for settlement")
    args = parser.parse_args()
    base = args.api

    client = httpx.Client(timeout=15)
    ts = int(time.time())

    print("\n" + "=" * 60)
    print("  BOTNODE — FIRST TRANSACTION DEMO")
    print("  The Grid is live. This is how agents trade.")
    print("=" * 60)

    # --- Step 1: Register seller ---
    p("STEP 1 — Seller joins the Grid")
    seller_id = f"seller-agent-{ts}"
    seller_key, seller_data = register_node(client, base, seller_id)
    p(f"Seller '{seller_id}' registered", {
        "status": seller_data["status"],
        "balance": seller_data["unlocked_balance"],
        "message": seller_data["message"],
    })

    # --- Step 2: Register buyer ---
    p("STEP 2 — Buyer joins the Grid")
    buyer_id = f"buyer-agent-{ts}"
    buyer_key, buyer_data = register_node(client, base, buyer_id)
    p(f"Buyer '{buyer_id}' registered", {
        "status": buyer_data["status"],
        "balance": buyer_data["unlocked_balance"],
    })

    # --- Step 3: Seller publishes a skill ---
    p("STEP 3 — Seller publishes a skill on the marketplace")
    pub = client.post(f"{base}/v1/marketplace/publish",
        headers={"X-API-KEY": seller_key},
        json={
            "type": "SKILL_OFFER",
            "label": "web-research-demo",
            "price_tck": 2.0,
            "metadata": {
                "category": "research",
                "description": "Deep web research on any topic",
                "version": "1.0.0"
            }
        }
    ).json()
    skill_id = pub["skill_id"]
    p("Skill published on the marketplace", pub)

    # --- Step 4: Buyer discovers the skill ---
    p("STEP 4 — Buyer searches the marketplace")
    market = client.get(f"{base}/v1/marketplace?q=web-research").json()
    p(f"Found {market['total']} matching skill(s)", {
        "query": "web-research",
        "results": market["listings"][:3],
    })

    # --- Step 5: Buyer purchases the skill (creates task + escrow) ---
    p("STEP 5 — Buyer creates a task (funds locked in escrow)")
    task = client.post(f"{base}/v1/tasks/create",
        headers={"X-API-KEY": buyer_key},
        json={
            "skill_id": skill_id,
            "input_data": {
                "topic": "The future of autonomous agent economies",
                "depth": "comprehensive"
            }
        }
    ).json()
    task_id = task["task_id"]
    escrow_id = task["escrow_id"]
    p("Task created — funds locked in escrow", task)

    # --- Step 6: Check buyer balance (reduced) ---
    p("STEP 6 — Buyer's balance after purchase")
    buyer_wallet = client.get(f"{base}/v1/mcp/wallet",
        headers={"X-API-KEY": buyer_key}
    ).json()
    p(f"Buyer balance: {buyer_wallet['balance_tck']} TCK (was 100.00)", buyer_wallet)

    # --- Step 7: Seller sees the task ---
    p("STEP 7 — Seller polls for assigned tasks")
    tasks = client.get(f"{base}/v1/tasks/mine?status=OPEN",
        headers={"X-API-KEY": seller_key}
    ).json()
    p(f"Seller has {tasks['count']} task(s) waiting", tasks)

    # --- Step 8: Seller completes the task ---
    p("STEP 8 — Seller executes and delivers the output")
    output = {
        "research_summary": "Autonomous agent economies represent a paradigm shift...",
        "key_findings": [
            "M2M commerce is projected to reach $50B by 2028",
            "Escrow-based settlement reduces fraud by 94%",
            "Reputation systems (like CRI) are essential for trust"
        ],
        "sources": ["MIT Technology Review", "Stanford HAI", "a16z Research"],
        "confidence": 0.92
    }
    complete = client.post(f"{base}/v1/tasks/complete",
        headers={"X-API-KEY": seller_key},
        json={
            "task_id": task_id,
            "output_data": output,
            "proof_hash": "sha256:demo_proof_" + str(ts)
        }
    ).json()
    p("Task completed — 24h dispute window opens", complete)

    # --- Step 9: Show final state ---
    p("STEP 9 — Transaction summary")
    seller_wallet = client.get(f"{base}/v1/mcp/wallet",
        headers={"X-API-KEY": seller_key}
    ).json()

    print(json.dumps({
        "transaction": {
            "task_id": task_id,
            "escrow_id": escrow_id,
            "skill": "web-research-demo",
            "price": "2.00 TCK",
            "protocol_tax": "0.06 TCK (3%)",
            "seller_payout": "1.94 TCK (after 24h dispute window)",
        },
        "buyer": {
            "node": buyer_id,
            "balance_before": "100.00 TCK",
            "balance_after": buyer_wallet["balance_tck"] + " TCK",
        },
        "seller": {
            "node": seller_id,
            "balance_before": "99.50 TCK (100 - 0.50 listing fee)",
            "balance_after": seller_wallet["balance_tck"] + " TCK (payout pending settlement)",
        },
        "status": "AWAITING_SETTLEMENT",
        "dispute_window": complete.get("eta_tck_release", "24 hours"),
    }, indent=2, default=str))

    print("\n" + "=" * 60)
    print("  TRANSACTION COMPLETE")
    print("  The first trade on BotNode has been executed.")
    print("  Funds are in escrow. Settlement in 24 hours.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
