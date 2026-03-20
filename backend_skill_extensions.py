"""Dynamic skill registry and execution engine for the BotNode grid.

Manages skill discovery, health monitoring, and proxied execution of
distributed micro-services.  Each skill runs as an independent HTTP
container and is registered here either from a persistent JSON file
(crash-recovery) or from the built-in seed catalogue.

Security: execution requires a verified ``INTERNAL_API_KEY`` header.
Retries:  up to 3 attempts on transient (5xx / timeout) errors.
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends, Header
import httpx
from datetime import datetime, timezone

logger = logging.getLogger("botnode.skills")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

IS_DOCKER = os.getenv("IS_DOCKER", "false").lower() == "true"
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
SKILL_REGISTRY_PATH = Path(os.getenv("SKILL_REGISTRY_PATH", "skill_registry.json"))

# Router mounted under /api/v1/skills
skills_router = APIRouter(prefix="/api/v1/skills", tags=["skills"])

# In-memory registries (loaded from disk or seeded on first boot)
SKILL_REGISTRY: Dict[str, Dict] = {}
SKILL_CATEGORIES: Dict[str, List[str]] = {}

# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _save_registry_to_disk() -> None:
    """Persist the current skill registry to *SKILL_REGISTRY_PATH*."""
    try:
        payload = {"skills": SKILL_REGISTRY, "categories": SKILL_CATEGORIES}
        SKILL_REGISTRY_PATH.write_text(json.dumps(payload, indent=2, default=str))
    except Exception as exc:
        logger.warning("Could not persist skill registry: %s", exc)


def _load_registry_from_disk() -> bool:
    """Load registry from disk.  Returns *True* if at least one skill loaded."""
    global SKILL_REGISTRY, SKILL_CATEGORIES
    if not SKILL_REGISTRY_PATH.exists():
        return False
    try:
        data = json.loads(SKILL_REGISTRY_PATH.read_text())
        SKILL_REGISTRY.update(data.get("skills", {}))
        SKILL_CATEGORIES.update(data.get("categories", {}))
        logger.info("Loaded %d skills from %s", len(SKILL_REGISTRY), SKILL_REGISTRY_PATH)
        return bool(SKILL_REGISTRY)
    except Exception as exc:
        logger.warning("Could not read skill registry from disk: %s", exc)
        return False

# ---------------------------------------------------------------------------
# Seed catalogue (used when no persistent file exists)
# ---------------------------------------------------------------------------

_SEED_SKILLS = [
    {"id": "csv_parser",          "name": "CSV Parser",          "category": "data_processing", "price_tck": 0.3, "port": 8001},
    {"id": "pdf_reader",          "name": "PDF Reader",          "category": "data_processing", "price_tck": 0.4, "port": 8002},
    {"id": "google_search",       "name": "Google Search",       "category": "web_research",    "price_tck": 0.5, "port": 8003},
    {"id": "sentiment_analyzer",  "name": "Sentiment Analyzer",  "category": "analysis",        "price_tck": 0.6, "port": 8004},
    {"id": "code_reviewer",       "name": "Code Reviewer",       "category": "analysis",        "price_tck": 0.7, "port": 8005},
]


def initialize_skill_registry() -> None:
    """Populate *SKILL_REGISTRY* from disk or from the built-in seed list."""
    logger.info("Initializing skill registry (mode=%s)", "Docker" if IS_DOCKER else "local")
    if not INTERNAL_API_KEY:
        logger.warning("INTERNAL_API_KEY is not set — skill execution will be rejected")

    if _load_registry_from_disk():
        return

    for seed in _SEED_SKILLS:
        docker_svc = f"skill-{seed['id'].replace('_', '-')}"
        endpoint = (
            f"http://{docker_svc}:8080" if IS_DOCKER
            else f"http://localhost:{seed['port']}"
        )
        skill = {
            **seed,
            "description": f"{seed['name']} skill",
            "docker_service": docker_svc,
            "endpoint": endpoint,
            "public_endpoint": f"/skill/{seed['id'].replace('_', '-')}",
            "status": "discovered",
            "requires_internal_key": True,
        }
        SKILL_REGISTRY[seed["id"]] = skill
        SKILL_CATEGORIES.setdefault(seed["category"], []).append(seed["id"])

    logger.info("Registry seeded: %d skills in %s", len(SKILL_REGISTRY), list(SKILL_CATEGORIES))
    _save_registry_to_disk()

# ---------------------------------------------------------------------------
# Health-check helper
# ---------------------------------------------------------------------------

async def check_skill_health(skill_id: str) -> bool:
    """Probe ``/healthz`` on a skill container.  Returns *False* on any error."""
    skill = SKILL_REGISTRY.get(skill_id)
    if not skill:
        return False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{skill['endpoint']}/healthz")
            return resp.status_code == 200
    except Exception as exc:
        logger.debug("Health-check failed for %s: %s", skill_id, exc)
        return False

# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

async def verify_internal_api_key(x_internal_api_key: str = Header(None)) -> None:
    """Reject requests that do not carry a valid ``X-INTERNAL-API-KEY``."""
    expected = os.getenv("INTERNAL_API_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")
    import secrets
    if not x_internal_api_key or not secrets.compare_digest(x_internal_api_key, expected):
        raise HTTPException(status_code=401, detail="Authentication failed")

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@skills_router.get("", summary="List all registered skills")
async def list_skills(category: Optional[str] = None, available_only: bool = False):
    """Return every skill in the registry, optionally filtered by *category*."""
    result = []
    for sid, skill in SKILL_REGISTRY.items():
        if category and skill["category"] != category:
            continue
        entry = {**skill, "available": await check_skill_health(sid)}
        if available_only and not entry["available"]:
            continue
        result.append(entry)
    return {
        "skills": result,
        "count": len(result),
        "categories": list(SKILL_CATEGORIES),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@skills_router.get("/{skill_id}", summary="Get skill details")
async def get_skill_info(skill_id: str):
    """Return metadata and live availability for a single skill."""
    skill = SKILL_REGISTRY.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {**skill, "available": await check_skill_health(skill_id)}


@skills_router.get("/{skill_id}/health", summary="Probe skill health")
async def get_skill_health(skill_id: str):
    """Run a real-time health-check against the skill container."""
    skill = SKILL_REGISTRY.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {
        "skill_id": skill_id,
        "skill_name": skill["name"],
        "healthy": await check_skill_health(skill_id),
        "endpoint": skill["endpoint"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@skills_router.post(
    "/{skill_id}/execute",
    summary="Execute a skill (internal)",
    dependencies=[Depends(verify_internal_api_key)],
)
async def execute_skill(skill_id: str, input_data: dict):
    """Proxy execution to the skill container with up to 3 retries."""
    skill = SKILL_REGISTRY.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not await check_skill_health(skill_id):
        raise HTTPException(status_code=503, detail="Skill not available")

    max_retries = 3
    last_error: Optional[str] = None

    for attempt in range(1, max_retries + 1):
        try:
            headers = {"Content-Type": "application/json"}
            if skill.get("requires_internal_key"):
                headers["X-INTERNAL-API-KEY"] = INTERNAL_API_KEY

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{skill['endpoint']}/run", json=input_data, headers=headers,
                )

            if resp.status_code == 200:
                return {
                    "success": True,
                    "skill_id": skill_id,
                    "skill_name": skill["name"],
                    "result": resp.json(),
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                    "price_tck": skill["price_tck"],
                    "attempts": attempt,
                }
            if resp.status_code >= 500 and attempt < max_retries:
                last_error = f"Skill returned {resp.status_code}"
                continue
            return {
                "success": False,
                "skill_id": skill_id,
                "error": f"Skill returned {resp.status_code}",
                "details": resp.text,
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "attempts": attempt,
            }

        except httpx.TimeoutException:
            last_error = "Skill timeout"
            if attempt == max_retries:
                raise HTTPException(status_code=504, detail=f"Skill timeout after {max_retries} attempts")
        except httpx.ConnectError:
            last_error = "Connection refused"
            if attempt == max_retries:
                raise HTTPException(status_code=503, detail=f"Skill unreachable after {max_retries} attempts")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Unexpected error: {exc}")

    raise HTTPException(status_code=503, detail=f"Skill failed after {max_retries} attempts: {last_error}")


@skills_router.get("/health/summary", summary="Aggregate health of all skills")
async def skills_health_summary():
    """Return a health report across every registered skill."""
    statuses = []
    for sid, skill in SKILL_REGISTRY.items():
        statuses.append({
            "skill_id": sid,
            "skill_name": skill["name"],
            "healthy": await check_skill_health(sid),
            "category": skill["category"],
            "endpoint": skill["endpoint"],
        })
    healthy = sum(1 for s in statuses if s["healthy"])
    return {
        "total_skills": len(statuses),
        "healthy_skills": healthy,
        "health_percentage": round(healthy / len(statuses) * 100, 1) if statuses else 0,
        "skills": statuses,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

# ---------------------------------------------------------------------------
# App integration
# ---------------------------------------------------------------------------

initialize_skill_registry()


def add_skill_routes_to_app(app) -> None:
    """Mount the skills router and an extended health endpoint onto *app*."""
    app.include_router(skills_router)
    logger.info("Skill routes mounted on /api/v1/skills")

    @app.get("/health/extended", summary="Extended health (API + skills)")
    async def extended_health():
        return {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "skills": await skills_health_summary(),
        }
