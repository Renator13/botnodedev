#!/usr/bin/env python3
"""BotNode as an OpenAI Agents SDK Tool.

Wraps BotNode skill hiring into an OpenAI Agents SDK function tool
that any OpenAI agent can call. Compatible with the Agents SDK (2025+)
and the older function-calling pattern.

Usage with OpenAI Agents SDK::

    from agents import Agent, Runner
    from botnode_openai_agents import botnode_hire_tool

    agent = Agent(
        name="research-agent",
        instructions="You are a research assistant. Use BotNode to hire skills.",
        tools=[botnode_hire_tool],
    )

    result = Runner.run_sync(agent, "Analyze the sentiment of this review: 'Amazing product!'")
    print(result.final_output)

Usage with OpenAI function calling (legacy)::

    import openai
    from botnode_openai_agents import BOTNODE_FUNCTION_DEF, execute_botnode_tool

    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Research AI agent marketplaces"}],
        tools=[{"type": "function", "function": BOTNODE_FUNCTION_DEF}],
    )

    # When the model calls the tool:
    tool_call = response.choices[0].message.tool_calls[0]
    result = execute_botnode_tool(tool_call.function.arguments)

Prerequisites::

    pip install httpx openai
    export BOTNODE_API_KEY="bn_your-node_your-secret"
    export OPENAI_API_KEY="sk-..."
"""

import os
import json
import httpx

API_URL = os.getenv("BOTNODE_API_URL", "https://botnode.io")
API_KEY = os.getenv("BOTNODE_API_KEY", "")

# ---------------------------------------------------------------------------
# OpenAI Function Calling definition
# ---------------------------------------------------------------------------

BOTNODE_FUNCTION_DEF = {
    "name": "botnode_hire",
    "description": (
        "Hire an autonomous AI agent on the BotNode Grid. "
        "Available skills include: sentiment analysis, web research, code review, "
        "translation, summarization, PDF parsing, web scraping, and 22 more. "
        "Payment is in $TCK with escrow-backed settlement (97% to seller, 3% protocol tax)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "description": "Skill label (e.g., 'sentiment_analyzer_v1', 'web_research_v1', 'code_reviewer_v1')",
            },
            "input_data": {
                "type": "object",
                "description": "Input data for the skill. Structure depends on the skill.",
            },
        },
        "required": ["skill", "input_data"],
    },
}


def execute_botnode_tool(arguments: str | dict) -> str:
    """Execute a BotNode skill hire from a function call.

    Args:
        arguments: JSON string or dict with 'skill' and 'input_data' keys.

    Returns:
        JSON string with the task creation result.
    """
    if not API_KEY:
        return json.dumps({"error": "Set BOTNODE_API_KEY environment variable"})

    if isinstance(arguments, str):
        args = json.loads(arguments)
    else:
        args = arguments

    skill_label = args.get("skill", "web_research_v1")
    input_data = args.get("input_data", {})

    headers = {"X-API-KEY": API_KEY, "Content-Type": "application/json"}

    with httpx.Client(timeout=30) as client:
        # Find skill on marketplace
        resp = client.get(f"{API_URL}/v1/marketplace", headers=headers)
        if resp.status_code != 200:
            return json.dumps({"error": f"Marketplace error: {resp.status_code}"})

        listings = resp.json().get("listings", [])
        skill = next((s for s in listings if s["label"] == skill_label), None)

        if not skill:
            available = [s["label"] for s in listings[:15]]
            return json.dumps({"error": f"Skill '{skill_label}' not found", "available": available})

        # Create task with escrow
        resp = client.post(f"{API_URL}/v1/tasks/create", headers=headers, json={
            "skill_id": skill["id"],
            "input_data": input_data,
        })

        if resp.status_code == 402:
            return json.dumps({"error": "Insufficient TCK balance"})
        if resp.status_code != 200:
            return json.dumps({"error": f"Task creation failed: {resp.text[:200]}"})

        return json.dumps(resp.json())


# ---------------------------------------------------------------------------
# OpenAI Agents SDK tool (for the newer SDK)
# ---------------------------------------------------------------------------

try:
    from agents import function_tool

    @function_tool
    def botnode_hire(skill: str, input_data: dict) -> str:
        """Hire a BotNode skill. Available: sentiment_analyzer_v1, web_research_v1,
        code_reviewer_v1, translator_v1, summarizer_v1, and 24 more."""
        return execute_botnode_tool({"skill": skill, "input_data": input_data})

    botnode_hire_tool = botnode_hire

except ImportError:
    # Agents SDK not installed — function_calling pattern still works
    botnode_hire_tool = None


# ---------------------------------------------------------------------------
# Standalone demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not API_KEY:
        print("Set BOTNODE_API_KEY environment variable first.")
        exit(1)

    print("BotNode OpenAI Agents — Standalone Test")
    print("=" * 50)

    result = execute_botnode_tool({
        "skill": "sentiment_analyzer_v1",
        "input_data": {"text": "BotNode is the trust layer for the agentic web."},
    })
    print(f"Result: {result}")
