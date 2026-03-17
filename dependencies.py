"""Shared dependencies, helpers, and constants for the BotNode API.

This module centralises objects that are used across multiple routers:
authentication dependencies, rate limiter, utility functions, path constants,
and shared state (e.g. the in-memory challenge store).
"""

import os
import secrets
import logging
import re
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape
from pathlib import Path

from fastapi import Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
from passlib.context import CryptContext

import models
import database
from auth.jwt_tokens import issue_access_token, verify_access_token

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
audit_log = logging.getLogger("botnode.audit")
logger = logging.getLogger("botnode.api")

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# Base URL & MCP capabilities
# ---------------------------------------------------------------------------
BASE_URL = os.getenv("BASE_URL", "https://botnode.io")

MCP_CAPABILITIES = {
    "web-research": {
        "skill_id": None,  # resolved by label fallback in mcp_hire
        "label_match": "web_research_v1",
        "description": "Deep web research with structured analysis.",
        "typical_price": 1.0,
        "eta_seconds": 30,
    },
    "pdf-summarizer": {
        "skill_id": None,  # resolved by label fallback in mcp_hire
        "label_match": "pdf_parser_v1",
        "description": "Extract text and metadata from PDF documents.",
        "typical_price": 0.4,
        "eta_seconds": 15,
    },
}

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# Challenge nonce store — DEPRECATED: challenges are now stored in the DB
# (models.PendingChallenge).  This symbol is kept as an empty dict so that
# any import of ``_pending_challenges`` in third-party or legacy code does
# not raise an ImportError.

# ---------------------------------------------------------------------------
# Database dependency
# ---------------------------------------------------------------------------
get_db = database.get_db

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
STATIC_ROOT = os.getenv("STATIC_ROOT", str(BASE_DIR / "static"))
DOCS_ROOT = os.path.join(STATIC_ROOT, "docs")
LEGAL_ROOT = os.path.join(STATIC_ROOT, "legal")
TRANSMISSIONS_ROOT = os.path.join(STATIC_ROOT, "transmissions")


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime for DB compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe_resolve(base: str, user_path: str) -> str | None:
    """Resolve *user_path* under *base*, returning ``None`` on traversal.

    Uses ``os.path.realpath`` to normalize symlinks and ``..`` segments,
    then verifies the result starts with the real base path.  This prevents
    attackers from reading arbitrary files via ``../../etc/passwd`` patterns.
    """
    resolved = os.path.realpath(os.path.join(base, user_path))
    if not resolved.startswith(os.path.realpath(base) + os.sep) and resolved != os.path.realpath(base):
        return None
    return resolved


def is_prime(n: int) -> bool:
    """Trial-division primality test.  Used to build registration challenges."""
    if n < 2: return False
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0: return False
    return True


def generate_status_badge_svg(node: models.Node, stats: dict) -> str:
    """Generate a simple SVG status badge for a node.

    Shows (MVP):
    - Genesis rank (if any)
    - CRI (Composite Reliability Index)
    - TX count (settled sales as seller)
    - Active days
    - Skills count
    """
    label = f"Genesis #{stats['rank']}" if stats.get("rank") else "Node"
    cri = stats.get("cri", 0)
    tx_count = stats.get("tx_count", 0)
    active_days = stats.get("active_days", 0)
    skills_count = stats.get("skills_count", 0)

    node_id = escape(node.id)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="460" height="80" role="img" aria-label="BotNode status badge for {node_id}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#050816"/>
      <stop offset="100%" stop-color="#111827"/>
    </linearGradient>
  </defs>
  <rect width="460" height="80" rx="10" fill="url(#bg)"/>
  <text x="16" y="22" fill="#e5e7eb" font-family="system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" font-size="13" font-weight="600">
    BotNode {label}
  </text>
  <text x="16" y="40" fill="#9ca3af" font-family="system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" font-size="11">
    {node_id}
  </text>
  <text x="16" y="60" fill="#f9fafb" font-family="system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" font-size="11">
    CRI: {cri} · TX: {tx_count} · Active: {active_days}d · Skills: {skills_count}
  </text>
</svg>"""
    return svg


# ---------------------------------------------------------------------------
# Authentication dependencies
# ---------------------------------------------------------------------------

def get_node(request: Request, db: Session = Depends(get_db)) -> models.Node:
    """FastAPI dependency: authenticate a node via the ``X-API-KEY`` header.

    Key format is ``bn_{node_id}_{secret}``.  The secret portion is verified
    against the PBKDF2-SHA256 hash stored in ``Node.api_key_hash``.

    Raises:
        HTTPException 401: on missing, malformed, or invalid key.
    """
    api_key = request.headers.get("X-API-KEY", "")
    if not api_key.startswith("bn_"):
        raise HTTPException(status_code=401, detail="Invalid API Key format")

    try:
        parts = api_key.split("_")
        node_id = parts[1]
        secret = parts[2]
    except IndexError:
        raise HTTPException(status_code=401, detail="Invalid API Key structure")

    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node or not node.active:
        raise HTTPException(status_code=401, detail="Node not found or banned")

    if not pwd_context.verify(secret, node.api_key_hash):
        raise HTTPException(status_code=401, detail="Authentication failed")

    return node


def get_current_node(request: Request, db: Session = Depends(get_db)) -> models.Node:
    """FastAPI dependency: authenticate via Bearer JWT **or** X-API-KEY fallback.

    Prefers the ``Authorization: Bearer <jwt>`` header.  Falls back to the
    legacy ``X-API-KEY`` header for backward compatibility.

    Returns:
        models.Node: the authenticated, active node.

    Raises:
        HTTPException 401: on any authentication failure.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return get_node(request, db)

    token = auth_header.replace("Bearer ", "")
    decoded = verify_access_token(token)

    if "error" in decoded:
        raise HTTPException(status_code=401, detail=decoded["error"])

    node_id = decoded["sub"]
    node = db.query(models.Node).filter(models.Node.id == node_id).first()

    if not node or not node.active:
        raise HTTPException(status_code=401, detail="Node not found or banned")

    return node


def verify_admin_token(token: str) -> bool:
    """Return *True* if *token* matches ``BOTNODE_ADMIN_TOKEN``.

    Uses ``secrets.compare_digest`` for constant-time comparison.
    Raises 503 if the env var is not configured.
    """
    expected = os.getenv("BOTNODE_ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin token not configured")
    return secrets.compare_digest(token, expected)


def require_admin_key(request: Request) -> bool:
    """FastAPI dependency: require ``Authorization: Bearer <ADMIN_KEY>`` header.

    Replaces the legacy query-param approach so that admin credentials never
    appear in URLs, server logs, or browser history.

    Raises:
        HTTPException 401/503: on missing or invalid credentials.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing admin Authorization header")
    key = auth.removeprefix("Bearer ")
    expected = os.getenv("ADMIN_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin key not configured")
    if not secrets.compare_digest(key, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True
