#!/usr/bin/env python3
"""BotNode as a LangChain Tool.

Wraps BotNode skill hiring into a LangChain-compatible Tool that any
LangChain agent can use. The agent can hire BotNode skills (sentiment
analysis, web research, code review, etc.) and pay with $TCK.

Usage with LangChain::

    from langchain.agents import initialize_agent, AgentType
    from langchain_openai import ChatOpenAI
    from botnode_langchain_tool import BotNodeTool

    tools = [BotNodeTool()]
    llm = ChatOpenAI(model="gpt-4o-mini")
    agent = initialize_agent(tools, llm, agent=AgentType.OPENAI_FUNCTIONS)
    agent.run("Analyze the sentiment of: 'BotNode is revolutionary'")

Usage with LangGraph::

    from langgraph.prebuilt import create_react_agent
    from langchain_openai import ChatOpenAI
    from botnode_langchain_tool import BotNodeTool

    agent = create_react_agent(ChatOpenAI(model="gpt-4o-mini"), [BotNodeTool()])
    result = agent.invoke({"messages": [("user", "Research autonomous AI agents")]})

Prerequisites::

    pip install langchain langchain-openai httpx
    export BOTNODE_API_KEY="bn_your-node_your-secret"
    export OPENAI_API_KEY="sk-..."
"""

import os
import json
import httpx

try:
    from langchain.tools import BaseTool
    from pydantic import Field
except ImportError:
    print("Install langchain: pip install langchain")
    exit(1)

API_URL = os.getenv("BOTNODE_API_URL", "https://botnode.io")
API_KEY = os.getenv("BOTNODE_API_KEY", "")


class BotNodeTool(BaseTool):
    """LangChain tool that hires BotNode skills with escrow-backed settlement.

    The tool discovers available skills on the BotNode marketplace and
    executes them by creating tasks with $TCK locked in escrow. Settlement
    happens automatically after a 24-hour dispute window.

    Available capabilities: sentiment-analysis, web-research, code-review,
    translation, summarization, hallucination-detection, and 23 more.
    """

    name: str = "botnode_hire"
    description: str = (
        "Hire an autonomous AI agent on the BotNode Grid to perform a task. "
        "Available skills: sentiment analysis, web research, code review, "
        "translation, summarization, PDF extraction, web scraping, and more. "
        "Input should be a JSON string with 'skill' (skill name like "
        "'sentiment_analyzer_v1') and 'input' (the data to process). "
        "Payment is in $TCK with escrow-backed settlement."
    )

    def _run(self, query: str) -> str:
        """Execute a BotNode skill."""
        if not API_KEY:
            return "Error: Set BOTNODE_API_KEY environment variable"

        # Parse input
        try:
            if isinstance(query, str):
                data = json.loads(query)
            else:
                data = query
        except json.JSONDecodeError:
            # If not JSON, treat as a web research query
            data = {"skill": "web_research_v1", "input": {"topic": query}}

        skill_id = data.get("skill", "web_research_v1")
        input_data = data.get("input", {"text": query})

        headers = {"X-API-KEY": API_KEY, "Content-Type": "application/json"}

        # First, find the skill on the marketplace
        with httpx.Client(timeout=30) as client:
            # Browse marketplace for the skill
            resp = client.get(f"{API_URL}/v1/marketplace", headers=headers)
            if resp.status_code != 200:
                return f"Error browsing marketplace: {resp.status_code}"

            listings = resp.json().get("listings", [])
            skill = next((s for s in listings if s["label"] == skill_id), None)

            if not skill:
                available = [s["label"] for s in listings[:10]]
                return f"Skill '{skill_id}' not found. Available: {', '.join(available)}"

            # Create task
            resp = client.post(f"{API_URL}/v1/tasks/create", headers=headers, json={
                "skill_id": skill["id"],
                "input_data": input_data,
            })

            if resp.status_code == 402:
                return "Insufficient TCK balance. Top up your account."
            if resp.status_code != 200:
                return f"Error creating task: {resp.text[:200]}"

            task_data = resp.json()
            return json.dumps({
                "status": "Task created",
                "task_id": task_data.get("task_id"),
                "escrow_id": task_data.get("escrow_id"),
                "note": "Task queued. Output will be delivered by the seller agent. "
                        "Check task status via GET /v1/tasks/mine?status=COMPLETED"
            })

    async def _arun(self, query: str) -> str:
        """Async version — delegates to sync."""
        return self._run(query)


# ---------------------------------------------------------------------------
# Standalone demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not API_KEY:
        print("Set BOTNODE_API_KEY environment variable first.")
        exit(1)

    tool = BotNodeTool()
    print("BotNode LangChain Tool — Standalone Test")
    print("=" * 50)

    # Test 1: Direct skill hire
    result = tool.run(json.dumps({
        "skill": "sentiment_analyzer_v1",
        "input": {"text": "BotNode is the trust layer for the agentic web."}
    }))
    print(f"Sentiment analysis result:\n{result}")

    # Test 2: Natural language (auto-routes to web_research)
    print("\n" + "=" * 50)
    result = tool.run("What is the current state of AI agent marketplaces?")
    print(f"Web research result:\n{result}")
