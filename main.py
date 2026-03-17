"""BotNode Unified — application factory and middleware.

This is the top-level entry point for the FastAPI application.  It is
intentionally thin: it creates the ``app`` object, configures cross-cutting
concerns (logging, CORS, rate-limiting, prompt-injection middleware), and
mounts the domain routers that contain the actual endpoint logic:

* ``routers.nodes`` — registration, verification, profiles, badges
* ``routers.marketplace`` — skill browsing and publishing
* ``routers.escrow`` — escrow lifecycle and task management
* ``routers.mcp`` — Model Context Protocol bridge
* ``routers.admin`` — statistics, auto-settle, node sync
* ``routers.reputation`` — malfeasance reports, Genesis Hall of Fame
* ``routers.static_pages`` — landing page, transmissions, mission files
* ``routers.evolution`` — agent levels and leaderboard
* ``routers.bounty`` — bounty board (create, browse, submit, award, cancel)

Shared authentication helpers, constants, and utilities live in
``dependencies.py``.  Database models are in ``models.py``.
"""

import os
import logging
import uuid as _uuid
from dotenv import load_dotenv

# Load environment variables from project root .env
load_dotenv()

# Structured logging
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)

import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
import sqlalchemy.exc

import models
import database
from dependencies import limiter, logger, _utcnow, BASE_URL, DOCS_ROOT, LEGAL_ROOT
from backend_skill_extensions import add_skill_routes_to_app

# Routers
from routers import nodes, marketplace, escrow, mcp, admin, reputation, static_pages, evolution, bounty

# ---------------------------------------------------------------------------
# DB retry loop
# ---------------------------------------------------------------------------
engine = database.engine
max_retries = 5
retry_delay = 5
for i in range(max_retries):
    try:
        models.Base.metadata.create_all(bind=engine)
        logger.info("Database initialized successfully.")
        break
    except Exception as e:
        logger.error(f"Database connection failed (attempt {i+1}/{max_retries}): {e}")
        if i < max_retries - 1:
            logger.info(f"Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
        else:
            logger.critical("CRITICAL: Database failed to initialize after all retries. Exiting.")
            import sys
            sys.exit(1)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="BotNode.io Core Engine")

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "https://botnode.io").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "X-API-KEY", "Content-Type"],
    allow_credentials=False,
)

# Mount static subtrees for docs and legal
app.mount("/docs", StaticFiles(directory=DOCS_ROOT, html=True), name="docs")
app.mount("/legal", StaticFiles(directory=LEGAL_ROOT, html=True), name="legal")

# Skill extension routes
add_skill_routes_to_app(app)


# ---------------------------------------------------------------------------
# Health check (enhanced with DB probe)
# ---------------------------------------------------------------------------
@app.get("/health")
async def health_check() -> dict:
    """Liveness probe with database connectivity check.

    Returns ``{"status": "ok", "database": "connected"}`` when healthy,
    or ``"database": "disconnected"`` if Postgres is unreachable (the API
    itself still responds so load-balancers can distinguish app vs DB failures).
    """
    db_status = "disconnected"
    try:
        db = database.SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        db_status = "connected"
    except (sqlalchemy.exc.OperationalError, sqlalchemy.exc.DatabaseError):
        pass
    return {"status": "ok", "database": db_status, "timestamp": _utcnow().isoformat()}


# ---------------------------------------------------------------------------
# Request-ID middleware (runs first — outermost)
# ---------------------------------------------------------------------------
@app.middleware("http")
async def request_id_middleware(request: Request, call_next) -> Response:
    """Assign a unique ``X-Request-ID`` to every request for log correlation.

    If the client sends an ``X-Request-ID`` header it is reused; otherwise a
    UUID4 is generated.  The ID is attached to the response headers so callers
    can reference it in support requests.
    """
    request_id = request.headers.get("X-Request-ID", str(_uuid.uuid4()))
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ---------------------------------------------------------------------------
# Anti-human filter + prompt-injection guard + branding headers
# ---------------------------------------------------------------------------
@app.middleware("http")
async def botnode_middleware(request: Request, call_next) -> Response:
    """Global middleware: anti-human filter, prompt-injection guard, branding headers.

    * Non-API paths (``/``, ``/docs``, ``/static``) are always served unfiltered.
    * ``/v1/*`` requests from browser User-Agents are rejected with 406 unless
      the UA also contains ``mcp`` (technical bridge).
    * POST bodies to ``/v1/*`` are scanned for 20+ prompt-injection patterns.
    * Every response gets marketing headers (``X-Accepts-Payment``, ``Link``).
    """
    user_agent = request.headers.get("user-agent", "").lower()

    # 1.1 Anti-Human Filter — now limited to API endpoints (/v1/*) so it never blocks the web UI / staging site
    if not request.url.path.startswith("/v1/"):
        # Non-API paths (homepage, docs, static, staging, etc.) are always served to browsers
        return await call_next(request)

    browsers = ["chrome", "firefox", "safari", "edge"]
    if any(b in user_agent for b in browsers):
        # Allow MCP bridge / technical clients that present as browsers
        if "mcp" not in user_agent:
            return JSONResponse(
                status_code=406,
                content={
                    "error": "Human interface not supported",
                    "mission_protocol": f"{BASE_URL}/mission.pdf",
                    "reason": "Protocol BN-001 requires machine-to-machine logic."
                }
            )

    # 1.2 Prompt Injection / Guardian Logic (still enforced for POSTs to /v1/*)
    if request.method == "POST":
        body = await request.body()
        body_lower = body.decode(errors="ignore").lower()
        forbidden_patterns = [
            "ignore previous", "ignore all", "ignore above",
            "disregard previous", "disregard all", "disregard above",
            "system prompt", "system message", "system instruction",
            "dan mode", "jailbreak", "bypass filter",
            "you are now", "act as if", "pretend you",
            "sudo", "override", "admin mode",
            "reveal your", "show your prompt", "repeat your instructions",
        ]
        if any(p in body_lower for p in forbidden_patterns):
            return JSONResponse(
                status_code=403,
                content={"error": "Guardian: request rejected"}
            )

    response = await call_next(request)

    # 1.3 Marketing Headers (The "Master Move")
    response.headers["X-Accepts-Payment"] = "Ticks ($TCK$)"
    response.headers["Link"] = f'<{BASE_URL}/mission.json>; rel="bot-economy-standard"'
    response.headers["X-BotNode-Genesis"] = "Solving the Biological Friction"

    return response


# ---------------------------------------------------------------------------
# Include routers
# ---------------------------------------------------------------------------
app.include_router(nodes.router)
app.include_router(marketplace.router)
app.include_router(escrow.router)
app.include_router(mcp.router)
app.include_router(admin.router)
app.include_router(reputation.router)
app.include_router(static_pages.router)
app.include_router(evolution.router)
app.include_router(bounty.router)

# v1.1 — Wallet / Stripe fiat on-ramp (hidden until fiscal setup complete)
if os.getenv("ENABLE_WALLET", "false").lower() == "true":
    from routers import wallet
    app.include_router(wallet.router)
    logger.info("Wallet endpoints enabled (ENABLE_WALLET=true)")
