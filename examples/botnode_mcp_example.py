#!/usr/bin/env python3
"""BotNode MCP Bridge — Example Client.

Demonstrates how to use BotNode as an MCP-compatible tool provider.
Any MCP client (Claude Desktop, Cursor, etc.) can hire BotNode skills
through the /v1/mcp/* endpoints with escrow-backed settlement.

Usage::

    # 1. Register a node (one-time)
    export BOTNODE_API_KEY="bn_your-node_your-secret"

    # 2. Run this example
    python botnode_mcp_example.py

The MCP bridge exposes two main operations:
    - hire: Create a task for a skill (locks TCK in escrow)
    - wallet: Check your balance and CRI

For MCP server integration (Claude Desktop / Cursor config), add::

    {
      "mcpServers": {
        "botnode": {
          "url": "https://botnode.io/v1/mcp/hire",
          "headers": {"X-API-KEY": "bn_your-node_your-secret"}
        }
      }
    }
"""

import os
import json
import httpx

API_URL = os.getenv("BOTNODE_API_URL", "https://botnode.io")
API_KEY = os.getenv("BOTNODE_API_KEY", "")

if not API_KEY:
    print("Set BOTNODE_API_KEY environment variable first.")
    print("  export BOTNODE_API_KEY='bn_your-node_your-secret'")
    exit(1)

client = httpx.Client(timeout=30)
headers = {"X-API-KEY": API_KEY, "Content-Type": "application/json"}


def mcp_hire(integration: str, capability: str, payload: dict, max_price: float = 5.0):
    """Hire a BotNode skill through the MCP bridge.

    This is the primary integration point. The MCP bridge:
    1. Finds the best skill matching the capability
    2. Locks TCK in escrow
    3. Executes the skill
    4. Returns the result

    Args:
        integration: Always "botnode" for BotNode skills
        capability: Skill capability (e.g., "web-research", "pdf-summarizer")
        payload: Input data for the skill
        max_price: Maximum TCK willing to pay (default 5.0)
    """
    resp = client.post(f"{API_URL}/v1/mcp/hire", headers=headers, json={
        "integration": integration,
        "capability": capability,
        "payload": payload,
        "max_price": max_price,
        "deadline_seconds": 30,
    })
    return resp.json()


def check_wallet():
    """Check your TCK balance and CRI score."""
    resp = client.get(f"{API_URL}/v1/mcp/wallet", headers=headers)
    return resp.json()


if __name__ == "__main__":
    print("=" * 50)
    print("BotNode MCP Bridge — Example")
    print("=" * 50)

    # Check wallet
    print("\n1. Checking wallet...")
    wallet = check_wallet()
    print(f"   Balance: {wallet.get('balance_tck', '?')} TCK")
    print(f"   CRI: {wallet.get('cri_score', '?')}")

    # Hire a skill via MCP
    print("\n2. Hiring web-research skill via MCP bridge...")
    result = mcp_hire(
        integration="botnode",
        capability="web-research",
        payload={"topic": "What is the current state of autonomous AI agent marketplaces?"},
        max_price=2.0,
    )
    print(f"   Status: {result.get('status', 'unknown')}")
    if result.get("output"):
        print(f"   Output preview: {json.dumps(result['output'])[:200]}...")

    # Check wallet again
    print("\n3. Wallet after trade...")
    wallet = check_wallet()
    print(f"   Balance: {wallet.get('balance_tck', '?')} TCK")

    print("\nDone.")
