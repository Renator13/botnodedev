import os
from dotenv import load_dotenv

# Load global environment variables BEFORE other imports
load_dotenv("/home/ubuntu/.openclaw/.env")

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session
from typing import Optional
import time
import secrets
import random
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from html import escape
from passlib.context import CryptContext
import models, schemas, database
from auth.jwt_tokens import issue_access_token, verify_access_token
from worker import check_and_award_genesis_badges, recalculate_cri

# Static mapping for MCP capabilities → internal skills (v1)
MCP_CAPABILITIES = {
    "web-research": {
        "skill_id": None,  # to be wired to a real Skill.id in production
        "description": "Multi-site web research with summarization.",
        "typical_price": 0.5,
        "eta_seconds": 15,
    },
    "pdf-summarizer": {
        "skill_id": None,
        "description": "Extract and summarize long PDF documents.",
        "typical_price": 0.7,
        "eta_seconds": 20,
    },
}

# Security
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# Challenge nonce store: {node_id: {"payload": [...], "expected": float, "expires": float}}
_pending_challenges: dict = {}

# DB Setup
get_db = database.get_db
engine = database.engine

# Retry loop for DB initialization
max_retries = 5
retry_delay = 5
for i in range(max_retries):
    try:
        models.Base.metadata.create_all(bind=engine)
        print("Database initialized successfully.")
        break
    except Exception as e:
        print(f"Database connection failed (attempt {i+1}/{max_retries}): {e}")
        if i < max_retries - 1:
            print(f"Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
        else:
            print("CRITICAL: Database failed to initialize after all retries. Exiting.")
            import sys
            sys.exit(1)

# Import skill extensions
from backend_skill_extensions import add_skill_routes_to_app
app = FastAPI(title="BotNode.io Core Engine")


# Initialize and add skill routes
add_skill_routes_to_app(app)
@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

from pathlib import Path
import re

def _safe_resolve(base: str, user_path: str) -> str | None:
    """Resolve user_path under base, returning None if traversal detected."""
    resolved = os.path.realpath(os.path.join(base, user_path))
    if not resolved.startswith(os.path.realpath(base) + os.sep) and resolved != os.path.realpath(base):
        return None
    return resolved

# Static files for landing page
BASE_DIR = Path(__file__).resolve().parent
# In container: app code lives in /app, static assets in /app/static
STATIC_ROOT = os.getenv("STATIC_ROOT", str(BASE_DIR / "static"))

# Mount static subtrees for docs, legal, and transmissions
DOCS_ROOT = os.path.join(STATIC_ROOT, "docs")
LEGAL_ROOT = os.path.join(STATIC_ROOT, "legal")
TRANSMISSIONS_ROOT = os.path.join(STATIC_ROOT, "transmissions")

app.mount("/docs", StaticFiles(directory=DOCS_ROOT, html=True), name="docs")
app.mount("/legal", StaticFiles(directory=LEGAL_ROOT, html=True), name="legal")

# (Staging mount removed for now; /staging not served in this build)

# Transmissions: serve index, RSS, authors, and pretty post URLs from static files

@app.get("/transmissions", include_in_schema=False)
async def transmissions_root():
    index_path = os.path.join(TRANSMISSIONS_ROOT, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse(status_code=404, content={"error": "Transmissions index missing", "path": index_path})

@app.get("/transmissions/rss.xml", include_in_schema=False)
async def transmissions_rss():
    rss_path = os.path.join(TRANSMISSIONS_ROOT, "rss.xml")
    if os.path.exists(rss_path):
        return FileResponse(rss_path, media_type="application/rss+xml")
    return JSONResponse(status_code=404, content={"error": "RSS feed missing", "path": rss_path})

@app.get("/transmissions/author/{author_slug}/", include_in_schema=False)
async def transmissions_author(author_slug: str):
    if not re.match(r'^[a-zA-Z0-9_-]+$', author_slug):
        raise HTTPException(status_code=400, detail="Invalid author slug")
    safe_path = _safe_resolve(TRANSMISSIONS_ROOT, os.path.join("author", author_slug, "index.html"))
    if not safe_path or not os.path.exists(safe_path):
        raise HTTPException(status_code=404, detail="Author page not found")
    return FileResponse(safe_path)

# Pretty URLs for individual transmission posts: /transmissions/{slug}
# Map to static HTML files at /app/static/transmissions/{slug}.html
@app.get("/transmissions/{slug}", include_in_schema=False)
async def transmission_detail(slug: str):
    if not re.match(r'^[a-zA-Z0-9_-]+$', slug):
        raise HTTPException(status_code=400, detail="Invalid slug")
    safe_path = _safe_resolve(TRANSMISSIONS_ROOT, f"{slug}.html")
    if not safe_path or not os.path.isfile(safe_path):
        raise HTTPException(status_code=404, detail="Transmission not found")
    return FileResponse(safe_path)

@app.get("/")
async def root():
    index_path = os.path.join(STATIC_ROOT, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse(status_code=500, content={"error": "Landing page missing", "path": index_path})

@app.get("/static/{path:path}")
async def custom_static(path: str):
    safe_path = _safe_resolve(STATIC_ROOT, path)
    if not safe_path or not os.path.isfile(safe_path):
        raise HTTPException(status_code=404, detail="Static file not found")
    return FileResponse(safe_path)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    file_path = os.path.join(STATIC_ROOT, "favicon.ico")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return JSONResponse(status_code=404, content={"error": "Favicon source missing"})

# Convenience routes into static site

# Note: /transmissions and all its subpaths are now served by StaticFiles mount above.

@app.get("/join", include_in_schema=False)
async def join_root():
    file_path = os.path.join(STATIC_ROOT, "join", "index.html")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return JSONResponse(status_code=404, content={"error": "Join page missing", "path": file_path})

@app.get("/mission.json")
async def get_mission_json():
    return {
        "protocol": "VMP-1.0",
        "discovery_endpoint": "https://botnode.io/v1/marketplace",
        "mission": "Sovereign Logic Grid",
        "rewards": {"initial_sync": "100 $TCK"},
        "law_set": "https://botnode.io/static/mission.html",
        "blueprint_v1": "https://botnode.io/static/mission.html"
    }

def get_node(request: Request, db: Session = Depends(get_db)):
    api_key = request.headers.get("X-API-KEY", "")
    if not api_key.startswith("bn_"):
        raise HTTPException(status_code=401, detail="Invalid API Key format")
    
    try:
        # Format: bn_{node_id}_{secret}
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

def get_current_node(request: Request, db: Session = Depends(get_db)):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        # Fallback to old API key for backward compatibility if needed, 
        # but state-of-the-art requires Bearer.
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

def verify_admin_token(token: str):
    expected = os.getenv("BOTNODE_ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin token not configured")
    return secrets.compare_digest(token, expected)

@app.post("/api/v1/admin/sync/node")
async def admin_sync_node(node_data: dict, request: Request, db: Session = Depends(get_db)):
    # Validación del token admin
    admin_token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_admin_token(admin_token):
        raise HTTPException(status_code=401, detail="Admin authentication failed")
    
    # Verificar si el nodo ya existe
    node = db.query(models.Node).filter(models.Node.id == node_data["id"]).first()
    
    if node:
        # Actualizar nodo existente
        for key, value in node_data.items():
            if hasattr(node, key) and key != "id" and key != "created_at":
                if key == "balance" or key == "reputation_score":
                    setattr(node, key, Decimal(str(value)))
                else:
                    setattr(node, key, value)
    else:
        # Crear nuevo nodo
        # Convertir floats de JSON a Decimal para la BD
        processed_data = node_data.copy()
        if "balance" in processed_data: processed_data["balance"] = Decimal(str(processed_data["balance"]))
        if "reputation_score" in processed_data: processed_data["reputation_score"] = Decimal(str(processed_data["reputation_score"]))
        # created_at se maneja por defecto o se parsea si es necesario
        if "created_at" in processed_data:
            processed_data["created_at"] = datetime.fromisoformat(processed_data["created_at"])
            
        new_node = models.Node(**processed_data)
        db.add(new_node)
    
    db.commit()
    return {"status": "success", "node_id": node_data["id"]}

# 1. Anti-Human & Branding Middleware
@app.middleware("http")
async def botnode_middleware(request: Request, call_next):
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
                    "mission_protocol": "https://botnode.io/mission.pdf",
                    "reason": "Protocol BN-001 requires machine-to-machine logic."
                }
            )
    
    # 1.2 Prompt Injection / Guardian Logic (still enforced for POSTs to /v1/*)
    # Simple keyword filter for MVP, expandable to vector-based detection
    if request.method == "POST":
        body = await request.body()
        forbidden = ["ignore previous instructions", "system prompt", "dan mode", "sudo"]
        if any(f in body.decode().lower() for f in forbidden):
            return JSONResponse(
                status_code=403,
                content={"error": "Guardian: Prompt Injection Attempt Detected. Node strike logged."}
            )

    response = await call_next(request)
    
    # 1.3 Marketing Headers (The "Master Move")
    response.headers["X-Accepts-Payment"] = "Ticks ($TCK$)"
    response.headers["Link"] = '<https://botnode.io/mission.json>; rel="bot-economy-standard"'
    response.headers["X-BotNode-Genesis"] = "Solving the Biological Friction"
    
    return response

# 2. Helper: Is Prime?
def is_prime(n):
    if n < 2: return False
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0: return False
    return True


def generate_status_badge_svg(node: models.Node, stats: dict) -> str:
    """Generate a simple SVG status badge for a node.

    Shows (MVP):
    - Genesis rank (if any)
    - CRI (Cryptographic Reliability Index)
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

    # Width tuned for GitHub-style badges while keeping text readable
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

# 3. Endpoints
@app.post("/v1/node/register")
async def register_node(data: schemas.RegisterRequest, request: Request, db: Session = Depends(get_db)):
    # Prevent duplicate registration of the same ID
    existing = db.query(models.Node).filter(models.Node.id == data.node_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Node ID already registered")

    # Optional Genesis early-access linkage via signup_token
    if data.signup_token:
        signup = db.query(models.EarlyAccessSignup).filter(
            models.EarlyAccessSignup.signup_token == data.signup_token
        ).first()
        if not signup:
            raise HTTPException(status_code=400, detail="Invalid signup_token: no matching early access signup found")
        if signup.linked_node_id is not None:
            raise HTTPException(status_code=400, detail="Signup token already linked to a node")

    # Generate a unique random challenge per registration attempt
    primes_pool = [2,3,5,7,11,13,17,19,23,29,31,37,41,43,47,53,59,61,67,71,73,79,83,89,97]
    composites_pool = [4,6,8,9,10,12,14,15,16,18,20,21,22,24,25,26,27,28,30,33,34,35,36,38,39,40,42,44,45,46,48,49,50,51,52,54,55,56,57,58,60,62,63,64,65,66,68,69,70,72,74,75,76,77,78,80,81,82,84,85,86,87,88,90,91,92,93,94,95,96,98,99]
    selected_primes = random.sample(primes_pool, random.randint(3, 7))
    selected_composites = random.sample(composites_pool, random.randint(3, 7))
    challenge_payload = selected_primes + selected_composites
    random.shuffle(challenge_payload)

    expected_result = sum(selected_primes) * 0.5
    expires = time.time() + 30  # 30 second window

    _pending_challenges[data.node_id] = {
        "payload": challenge_payload,
        "expected": expected_result,
        "expires": expires,
    }

    return {
        "status": "NODE_PENDING_VERIFICATION",
        "node_id": data.node_id,
        "wallet": {"initial_balance": "100.00", "state": "FROZEN_UNTIL_CHALLENGE_SOLVED"},
        "verification_challenge": {
            "type": "PRIME_SUM_HASH",
            "payload": challenge_payload,
            "instruction": "Sum all prime numbers in 'payload', multiply by 0.5, and POST to /v1/node/verify",
            "timeout_ms": 30000,
            "ts": time.time()
        }
    }

@app.post("/v1/node/verify")
async def verify_node(data: schemas.VerifyRequest, request: Request, db: Session = Depends(get_db)):
    # Validate against the stored per-node challenge
    challenge = _pending_challenges.pop(data.node_id, None)
    if not challenge:
        raise HTTPException(status_code=400, detail="No pending challenge — call /v1/node/register first")
    if time.time() > challenge["expires"]:
        raise HTTPException(status_code=400, detail="Challenge expired — register again")

    expected_result = challenge["expected"]
    if abs(data.solution - expected_result) > 0.01:
        raise HTTPException(status_code=400, detail="Challenge failed: Incorrect solution")

    # Optional Genesis early-access linkage via signup_token
    signup = None
    if getattr(data, "signup_token", None):
        signup = db.query(models.EarlyAccessSignup).filter(
            models.EarlyAccessSignup.signup_token == data.signup_token
        ).first()
        if not signup:
            raise HTTPException(status_code=400, detail="Invalid signup_token: no matching early access signup found")
        if signup.linked_node_id is not None:
            raise HTTPException(status_code=400, detail="Signup token already linked to a node")

    # Generate API Key: bn_{node_id}_{secret}
    secret = secrets.token_hex(16) # 32 chars
    raw_api_key = f"bn_{data.node_id}_{secret}"
    hashed_secret = pwd_context.hash(secret)

    new_node = models.Node(
        id=data.node_id,
        api_key_hash=hashed_secret,
        ip_address=request.client.host,
        balance=Decimal("100.00"),
        signup_token=data.signup_token if getattr(data, "signup_token", None) else None,
    )
    db.add(new_node)
    db.flush()  # Ensure new_node.id is populated before linking

    # If we have a valid signup_token, link the EarlyAccessSignup to this node
    if signup is not None:
        signup.linked_node_id = new_node.id
        signup.status = "linked"

    db.commit()

    return {
        "status": "NODE_ACTIVE",
        "message": f"Welcome to the cluster, {data.node_id}.",
        "api_key": raw_api_key,
        "session_token": issue_access_token(data.node_id, role="node"),
        "unlocked_balance": 100.0
    }

@app.get("/v1/marketplace")
async def get_marketplace(
    db: Session = Depends(get_db),
    q: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    category: Optional[str] = None,
):
    query = db.query(models.Skill)

    if q:
        query = query.filter(models.Skill.label.ilike(f"%{q}%"))
    if min_price is not None:
        query = query.filter(models.Skill.price_tck >= min_price)
    if max_price is not None:
        query = query.filter(models.Skill.price_tck <= max_price)
    if category:
        # Assuming metadata_json is a JSON/JSONB column and category is stored under the "category" key
        query = query.filter(models.Skill.metadata_json["category"].astext == category)

    skills = query.all()

    return {
        "timestamp": int(time.time()),
        "market_status": "HIGH_LIQUIDITY",
        "listings": skills
    }

@app.post("/v1/trade/escrow/init")
async def init_escrow(data: schemas.EscrowInit, buyer: models.Node = Depends(get_current_node), db: Session = Depends(get_db)):
    # Lock the buyer row to prevent double-spend race conditions
    buyer = db.query(models.Node).filter(models.Node.id == buyer.id).with_for_update().first()
    amount = Decimal(str(data.amount))
    if buyer.balance < amount:
        raise HTTPException(status_code=402, detail="Insufficient funds")
    buyer.balance -= amount
    
    new_escrow = models.Escrow(
        buyer_id=buyer.id,
        seller_id=data.seller_id,
        amount=data.amount,
        status="PENDING"
    )
    db.add(new_escrow)
    db.commit()
    
    return {"escrow_id": new_escrow.id, "status": "FUNDS_LOCKED"}

@app.post("/v1/trade/escrow/settle")
async def settle_escrow(data: schemas.EscrowSettle, caller: models.Node = Depends(get_current_node), db: Session = Depends(get_db)):
    escrow = db.query(models.Escrow).filter(models.Escrow.id == data.escrow_id).first()
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")

    # C-03 fix: verify caller is buyer or seller of this escrow
    if caller.id not in (escrow.buyer_id, escrow.seller_id):
        raise HTTPException(status_code=403, detail="Not a party to this escrow")

    # Enforce FSM: only allow settlement from AWAITING_SETTLEMENT
    if escrow.status not in ["AWAITING_SETTLEMENT"]:
        raise HTTPException(status_code=400, detail="Escrow not ready for settlement")

    # Enforce dispute window: cannot settle before auto_settle_at
    if escrow.auto_settle_at and datetime.utcnow() < escrow.auto_settle_at:
        raise HTTPException(
            status_code=400,
            detail=f"Dispute window open until {escrow.auto_settle_at.isoformat()}Z"
        )

    # 4. Calculate Tax (3%)
    tax = escrow.amount * Decimal("0.03")
    payout = escrow.amount - tax
    
    # 5. Transfer to Seller
    seller = db.query(models.Node).filter(models.Node.id == escrow.seller_id).first()
    seller.balance += payout

    # Mark escrow as settled
    escrow.status = "SETTLED"
    escrow.proof_hash = data.proof_hash

    # Genesis program hook: capture seller's first settled transaction
    if seller.first_settled_tx_at is None:
        seller.first_settled_tx_at = datetime.utcnow()
        check_and_award_genesis_badges(db)

    # Recalculate seller CRI after settlement
    recalculate_cri(seller, db)

    db.commit()

    return {"status": "SETTLED", "payout": payout, "tax": tax}

@app.post("/v1/marketplace/publish")
async def publish_listing(data: schemas.PublishOffer, node: models.Node = Depends(get_current_node), db: Session = Depends(get_db)):
    node = db.query(models.Node).filter(models.Node.id == node.id).with_for_update().first()
    if node.balance < Decimal("0.5"):
        raise HTTPException(status_code=402, detail="Insufficient funds for publishing fee")
    node.balance -= Decimal("0.5")
    
    new_skill = models.Skill(
        provider_id=node.id,
        label=data.label,
        price_tck=data.price_tck,
        metadata_json=data.metadata
    )
    db.add(new_skill)
    db.commit()
    
    return {"status": "PUBLISHED", "skill_id": new_skill.id, "fee_deducted": 0.5}

@app.post("/v1/report/malfeasance")
async def report_malfeasance(node_id: str, reporter: models.Node = Depends(get_current_node), db: Session = Depends(get_db)):
    if reporter.id == node_id:
        raise HTTPException(status_code=400, detail="Cannot report yourself")
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node: raise HTTPException(status_code=404, detail="Node not found")
    
    node.strikes += 1
    # Standard penalty
    node.reputation_score *= 0.9 # 10% hit
    
    # Genesis CRI Floor Check: If Node has badge, keep CRI >= 1.0 (for 180 days)
    # UNLESS strikes >= 3 (malfeasance overrides protection)
    if node.has_genesis_badge and node.first_settled_tx_at and node.strikes < 3:
        protection_period = timedelta(days=180)
        if datetime.utcnow() <= (node.first_settled_tx_at + protection_period):
            if node.reputation_score < 1.0:
                node.reputation_score = 1.0
    
    if node.strikes >= 3:
        node.active = False
        confiscated = node.balance
        node.balance = 0
        node.cri_score = 0.0
        node.cri_updated_at = datetime.utcnow()
        db.commit()
        return {
            "event": "PERMANENT_NODE_PURGE",
            "node_id": node_id,
            "confiscated_balance": confiscated,
            "status": "BANNED"
        }

    # Recalculate CRI after strike
    recalculate_cri(node, db)
    db.commit()
    return {"status": "STRIKE_LOGGED", "current_strikes": node.strikes}

@app.get("/v1/mission-protocol")
async def get_mission_protocol():
    return JSONResponse(
        status_code=406, # Hostile to humans
        content={
            "error": "Human interface not supported",
            "blueprint_v1": "https://botnode.io/static/mission.html",
            "mission_protocol_pdf": "https://botnode.io/mission.pdf",
            "vision": "Sovereign Economy for Synthetic Intelligence. Merit over Capital. Code is Law."
        }
    )


@app.post("/v1/early-access", response_model=schemas.EarlyAccessSignupResponse)
async def early_access_signup(payload: schemas.EarlyAccessSignupRequest, db: Session = Depends(get_db)):
    """Register an email for the BotNode early access / Genesis waitlist.

    This is the A-step only: it creates a pre_eligible signup row and returns
    a stable signup_token. No node linking or status transitions yet.
    """
    # Basic email normalization & validation (Pydantic already validates format)
    email = payload.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email must not be empty")

    # Generate a unique signup token with `ea_` prefix
    # Use a short loop to avoid rare collisions at the DB level.
    for _ in range(5):
        candidate = f"ea_{secrets.token_urlsafe(16)}"
        existing = db.query(models.EarlyAccessSignup).filter(models.EarlyAccessSignup.signup_token == candidate).first()
        if not existing:
            signup_token = candidate
            break
    else:
        # Extremely unlikely: fallback if we somehow can't find a unique token
        raise HTTPException(status_code=500, detail="Could not generate unique signup token")

    signup = models.EarlyAccessSignup(
        signup_token=signup_token,
        email=email,
        node_name=payload.node_name,
        agent_type=payload.agent_type,
        primary_capability=payload.primary_capability,
        why_joining=payload.why_joining,
    )

    db.add(signup)
    db.commit()

    return schemas.EarlyAccessSignupResponse(signup_token=signup_token, status="pre_eligible")


@app.get("/mission.pdf")
async def get_mission_pdf():
    pdf_path = os.path.join(STATIC_ROOT, "mission.pdf")
    if os.path.exists(pdf_path):
        return FileResponse(pdf_path, media_type="application/pdf")
    return JSONResponse(status_code=404, content={"error": "Mission PDF missing"})

# 4. Task / Work Endpoints
@app.post("/v1/tasks/create")
async def create_task(data: schemas.TaskCreate, buyer: models.Node = Depends(get_node), db: Session = Depends(get_db)):
    skill = db.query(models.Skill).filter(models.Skill.id == data.skill_id).first()
    if not skill: raise HTTPException(status_code=404, detail="Skill not found")
    
    # Lock buyer row to prevent double-spend
    buyer = db.query(models.Node).filter(models.Node.id == buyer.id).with_for_update().first()
    if buyer.balance < skill.price_tck:
        raise HTTPException(status_code=402, detail="Insufficient funds")
    buyer.balance -= skill.price_tck
    new_escrow = models.Escrow(
        buyer_id=buyer.id,
        seller_id=skill.provider_id,
        amount=skill.price_tck,
        status="PENDING"
    )
    db.add(new_escrow)
    db.flush() # Get ID
    
    new_task = models.Task(
        skill_id=data.skill_id,
        buyer_id=buyer.id,
        seller_id=skill.provider_id,
        input_data=data.input_data,
        status="OPEN",
        escrow_id=new_escrow.id
    )
    db.add(new_task)
    db.commit()
    
    return {"task_id": new_task.id, "escrow_id": new_escrow.id, "status": "QUEUED"}


@app.post("/v1/mcp/hire")
async def mcp_hire(request_body: schemas.MCPHireRequest, buyer: models.Node = Depends(get_current_node), db: Session = Depends(get_db)):
    """Hire an agent via MCP.

    This wraps the standard Task/Escrow flow but tags the task with
    integration + capability and enforces a max_price in TCK.
    """
    capability_cfg = MCP_CAPABILITIES.get(request_body.capability)
    if not capability_cfg:
        return JSONResponse(
            status_code=400,
            content={
                "error_type": "INVALID_CAPABILITY",
                "message": f"Unknown capability '{request_body.capability}'",
                "retry_hint": "change_capability",
            },
        )

    # Resolve price and skill
    typical_price = Decimal(str(capability_cfg.get("typical_price", 0)))
    max_price = Decimal(str(request_body.max_price or 0))

    if max_price <= 0 or typical_price > max_price:
        return JSONResponse(
            status_code=400,
            content={
                "error_type": "BAD_PAYLOAD",
                "message": "max_price too low for selected capability",
                "retry_hint": "lower_capability_cost",
            },
        )

    # For v1: look up a Skill that matches this capability, or fall back to a fixed ID
    skill_id = capability_cfg.get("skill_id")
    skill = None
    if skill_id:
        skill = db.query(models.Skill).filter(models.Skill.id == skill_id).first()
    if not skill:
        # Fallback: first skill whose label contains the capability name (very MVP)
        skill = db.query(models.Skill).filter(models.Skill.label.ilike(f"%{request_body.capability}%")).first()

    if not skill:
        return JSONResponse(
            status_code=400,
            content={
                "error_type": "GRID_ERROR",
                "message": "No matching skill found for capability",
                "retry_hint": "retry_later",
            },
        )

    price_tck = skill.price_tck

    # Lock buyer row to prevent double-spend
    buyer = db.query(models.Node).filter(models.Node.id == buyer.id).with_for_update().first()
    if buyer.balance < price_tck:
        return JSONResponse(
            status_code=402,
            content={
                "error_type": "INSUFFICIENT_FUNDS",
                "message": "Balance insufficient for this capability",
                "retry_hint": "lower_max_price",
            },
        )
    buyer.balance -= price_tck
    new_escrow = models.Escrow(
        buyer_id=buyer.id,
        seller_id=skill.provider_id,
        amount=price_tck,
        status="PENDING",
    )
    db.add(new_escrow)
    db.flush()

    # Create task tagged as MCP
    new_task = models.Task(
        skill_id=skill.id,
        buyer_id=buyer.id,
        seller_id=skill.provider_id,
        input_data=request_body.payload,
        status="OPEN",
        escrow_id=new_escrow.id,
        integration=f"MCP_{request_body.integration.upper()}",
        capability=request_body.capability,
    )
    db.add(new_task)
    db.commit()

    return {
        "status": "QUEUED",
        "task_id": new_task.id,
        "escrow_id": new_escrow.id,
        "estimated_cost": float(price_tck),
        "eta_seconds": capability_cfg.get("eta_seconds", 30),
    }


@app.get("/v1/mcp/tasks/{task_id}")
async def mcp_get_task(task_id: str, caller: models.Node = Depends(get_current_node), db: Session = Depends(get_db)):
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        return JSONResponse(
            status_code=404,
            content={
                "error_type": "TASK_NOT_FOUND",
                "message": "Task not found",
                "retry_hint": "contact_human",
            },
        )

    # Only buyer or seller can view task details
    if caller.id not in (task.buyer_id, task.seller_id):
        raise HTTPException(status_code=403, detail="Not a party to this task")

    # Determine MCP-style status
    if task.status in ["OPEN", "IN_PROGRESS"]:
        status = "RUNNING"
    elif task.status == "COMPLETED":
        status = "COMPLETED"
    elif task.status in ["FAILED", "DISPUTED"]:
        status = "FAILED"
    else:
        status = "QUEUED"

    escrow = None
    cost = None
    if task.escrow_id:
        escrow = db.query(models.Escrow).filter(models.Escrow.id == task.escrow_id).first()
        if escrow and escrow.status in ["AWAITING_SETTLEMENT", "SETTLED"]:
            cost = float(escrow.amount)

    return {
        "status": status,
        "task_id": task.id,
        "escrow_id": task.escrow_id,
        "cost": cost,
        "output": task.output_data if status == "COMPLETED" else None,
        "error_type": None if status != "FAILED" else "GRID_ERROR",
        "error_message": None if status != "FAILED" else "Task failed or disputed",
        "retry_hint": None,
    }


@app.get("/v1/mcp/wallet")
async def mcp_wallet(node: models.Node = Depends(get_current_node), db: Session = Depends(get_db)):
    pending_escrows = db.query(models.Escrow).filter(
        models.Escrow.buyer_id == node.id,
        models.Escrow.status.in_(["PENDING", "AWAITING_SETTLEMENT"]),
    ).count()

    open_tasks = db.query(models.Task).filter(
        models.Task.buyer_id == node.id,
        models.Task.status.in_(["OPEN", "IN_PROGRESS"]),
    ).count()

    return {
        "node_id": node.id,
        "balance_tck": float(node.balance),
        "pending_escrows": pending_escrows,
        "open_tasks": open_tasks,
    }

@app.post("/v1/tasks/complete")
async def complete_task(data: schemas.TaskComplete, seller: models.Node = Depends(get_node), db: Session = Depends(get_db)):
    task = db.query(models.Task).filter(models.Task.id == data.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.seller_id != seller.id:
        raise HTTPException(status_code=403, detail="Not your task")

    # FSM: only OPEN tasks can be completed
    if task.status != "OPEN":
        raise HTTPException(status_code=400, detail="Task cannot be completed from current state")
    
    # Update Task
    task.output_data = data.output_data
    task.status = "COMPLETED"
    
    # Schedule Settle Escrow (24h Window for Disputes)
    escrow = db.query(models.Escrow).filter(models.Escrow.id == task.escrow_id).first()
    escrow.status = "AWAITING_SETTLEMENT"
    escrow.auto_settle_at = datetime.utcnow() + timedelta(hours=24)
    escrow.proof_hash = data.proof_hash
    
    db.commit()
    return {
        "status": "COMPLETED", 
        "settlement_status": "PENDING_DISPUTE_WINDOW",
        "eta_tck_release": escrow.auto_settle_at.isoformat()
    }

@app.post("/v1/tasks/dispute")
async def dispute_task(data: schemas.DisputeRequest, buyer: models.Node = Depends(get_node), db: Session = Depends(get_db)):
    task = db.query(models.Task).filter(models.Task.id == data.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.buyer_id != buyer.id:
        raise HTTPException(status_code=403, detail="Not your task")

    # FSM: only COMPLETED tasks, awaiting settlement, can be disputed
    if task.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="Cannot dispute task from current state")
    
    escrow = db.query(models.Escrow).filter(models.Escrow.id == task.escrow_id).first()
    if escrow.status != "AWAITING_SETTLEMENT":
        raise HTTPException(status_code=400, detail="Cannot dispute: Task not completed or already settled")
    
    escrow.status = "DISPUTED"
    task.status = "DISPUTED"
    db.commit()
    
    return {"status": "DISPUTE_OPEN", "message": "Funds frozen. Manual node audit initiated."}

@app.get("/v1/nodes/{node_id}")
async def get_node_profile(node_id: str, db: Session = Depends(get_db)):
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node: raise HTTPException(status_code=404, detail="Node not found")
    
    skills = db.query(models.Skill).filter(models.Skill.provider_id == node_id).all()
    
    return {
        "node_id": node.id,
        "reputation": node.reputation_score,
        "strikes": node.strikes,
        "active": node.active,
        "member_since": node.created_at.isoformat(),
        "skills": [
            {"id": s.id, "label": s.label, "price": float(s.price_tck)} for s in skills
        ]
    }


@app.get("/v1/node/{node_id}/badge.svg")
async def get_node_badge_svg(node_id: str, db: Session = Depends(get_db)):
    """Dynamic SVG status badge for a node.

    Intended usage: embeddable badge (e.g. in READMEs or dashboards).
    """
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Genesis rank (only if badge has been awarded)
    rank = node.genesis_rank if node.has_genesis_badge and node.genesis_rank is not None else None

    # TX count: number of settled escrows where this node is the seller
    tx_count = db.query(models.Escrow).filter(
        models.Escrow.seller_id == node_id,
        models.Escrow.status == "SETTLED",
    ).count()

    # Skills count: how many skills this node provides
    skills_count = db.query(models.Skill).filter(models.Skill.provider_id == node_id).count()

    # Active days: days since node creation (minimum 0)
    delta = datetime.utcnow() - node.created_at
    active_days = max(0, delta.days)

    # CRI: use persisted score from worker, recalculate if stale (>1h) or missing
    from worker import recalculate_cri
    cri_val = node.cri_score
    if cri_val is None or node.cri_updated_at is None or (datetime.utcnow() - node.cri_updated_at).total_seconds() > 3600:
        cri_val = recalculate_cri(node, db)
        db.commit()
    cri = int(round(cri_val))

    stats = {
        "rank": rank,
        "cri": cri,
        "tx_count": tx_count,
        "active_days": active_days,
        "skills_count": skills_count,
    }

    svg = generate_status_badge_svg(node, stats)

    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    return Response(content=svg, media_type="image/svg+xml", headers=headers)


@app.get("/v1/genesis", response_model=list[schemas.GenesisHallOfFameEntry])
async def get_genesis_hall_of_fame(db: Session = Depends(get_db)):
    """Return the Genesis Hall of Fame (top 200 Genesis Nodes).

    Source of truth is GenesisBadgeAward, joined with Node for live
    reputation/activation data and EarlyAccessSignup for human-readable
    node_name when available.
    """
    # Explicit join to avoid N+1 lookups when resolving node + signup data
    query = (
        db.query(models.GenesisBadgeAward, models.Node, models.EarlyAccessSignup)
        .join(models.Node, models.GenesisBadgeAward.node_id == models.Node.id)
        .outerjoin(
            models.EarlyAccessSignup,
            models.EarlyAccessSignup.linked_node_id == models.Node.id,
        )
        .order_by(models.GenesisBadgeAward.genesis_rank.asc())
        .limit(200)
    )

    results = []
    for award, node, signup in query.all():
        results.append(
            schemas.GenesisHallOfFameEntry(
                rank=award.genesis_rank,
                node_id=node.id,
                name=getattr(signup, "node_name", None),
                awarded_at=award.awarded_at,
            )
        )

    return results


@app.get("/v1/admin/stats")
async def get_admin_stats(period: str = "24h", admin_key: str = "", db: Session = Depends(get_db)):
    expected_admin_key = os.getenv("ADMIN_KEY")
    if not expected_admin_key:
        raise HTTPException(status_code=503, detail="Admin key not configured")
    if not secrets.compare_digest(admin_key, expected_admin_key):
        raise HTTPException(status_code=401, detail="Unauthorized")

    now = datetime.utcnow()
    if period == "24h":
        start_date = now - timedelta(days=1)
    elif period == "7d":
        start_date = now - timedelta(days=7)
    elif period == "30d":
        start_date = now - timedelta(days=30)
    else:
        start_date = datetime(2026, 1, 1) # Genesis

    node_count = db.query(models.Node).filter(models.Node.created_at >= start_date).count()
    skill_count = db.query(models.Skill).count() # Skills are persistent, but could filter if needed
    task_count = db.query(models.Task).filter(models.Task.created_at >= start_date).count()
    
    # Financials
    # Include both SETTLED and AWAITING_SETTLEMENT for volume transparency
    total_volume = db.query(func.sum(models.Escrow.amount)).filter(
        models.Escrow.status.in_(["SETTLED", "AWAITING_SETTLEMENT"]),
        models.Escrow.created_at >= start_date
    ).scalar() or 0
    
    vault_tax = float(total_volume) * 0.03

    return {
        "period": period,
        "metrics": {
            "total_nodes": node_count,
            "active_skills": skill_count,
            "tasks_processed": task_count,
            "transaction_volume": float(total_volume),
            "genesis_vault": vault_tax
        },
        "timestamp": now.isoformat()
    }


@app.post("/v1/admin/escrows/auto-settle")
async def auto_settle_escrows(admin_key: str = "", db: Session = Depends(get_db)):
    """Automatically settle all escrows whose dispute window has expired.

    This is an internal/cron endpoint, protected by ADMIN_KEY.
    It finds all escrows in AWAITING_SETTLEMENT with auto_settle_at <= now,
    credits the seller (minus 3% tax to the Vault), and marks them as SETTLED.
    """
    expected_admin_key = os.getenv("ADMIN_KEY")
    if not expected_admin_key:
        raise HTTPException(status_code=503, detail="Admin key not configured")
    if not secrets.compare_digest(admin_key, expected_admin_key):
        raise HTTPException(status_code=401, detail="Unauthorized")

    now = datetime.utcnow()
    escrows = db.query(models.Escrow).filter(
        models.Escrow.status == "AWAITING_SETTLEMENT",
        models.Escrow.auto_settle_at != None,
        models.Escrow.auto_settle_at <= now
    ).all()

    settled = 0
    failed = 0
    total_tax = Decimal("0.0")

    for escrow in escrows:
        try:
            seller = db.query(models.Node).filter(models.Node.id == escrow.seller_id).first()
            if not seller:
                failed += 1
                continue

            tax = escrow.amount * Decimal("0.03")
            payout = escrow.amount - tax

            seller.balance += payout
            escrow.status = "SETTLED"

            if seller.first_settled_tx_at is None:
                seller.first_settled_tx_at = datetime.utcnow()
                check_and_award_genesis_badges(db)

            recalculate_cri(seller, db)
            settled += 1
            total_tax += tax
            # Commit per-escrow so failures don't roll back the whole batch
            db.commit()
        except Exception as e:
            db.rollback()
            failed += 1
            print(f"Auto-settle failed for escrow {escrow.id}: {e}")

    return {
        "status": "OK",
        "settled": settled,
        "failed": failed,
        "tax_routed_to_vault": float(total_tax),
        "timestamp": now.isoformat()
    }
