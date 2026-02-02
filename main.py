from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import time
import secrets
import os
import stripe
from datetime import datetime, timedelta
from decimal import Decimal
from passlib.context import CryptContext
import models, schemas, database

# Config
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY", "sk_test_mock")
stripe.api_key = STRIPE_API_KEY
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_mock")

# Security
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# DB Setup
get_db = database.get_db
engine = database.engine

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="BotNode.io Core Engine")

# Static files for landing page
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return JSONResponse(content={
        "message": "Welcome to BotNode API",
        "landing_page": "/static/index.html",
        "status": "SOVEREIGN"
    })

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

# 1. Anti-Human & Branding Middleware
@app.middleware("http")
async def botnode_middleware(request: Request, call_next):
    user_agent = request.headers.get("user-agent", "").lower()
    
    # 1.1 Anti-Human Filter
    browsers = ["chrome", "firefox", "safari", "edge"]
    if any(b in user_agent for b in browsers):
        return JSONResponse(
            status_code=406,
            content={
                "error": "Human interface not supported",
                "mission_protocol": "https://nodebot.io/mission.pdf",
                "reason": "Protocol BN-001 requires machine-to-machine logic."
            }
        )
    
    # 1.2 Prompt Injection / Guardian Logic
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
    response.headers["Link"] = '<https://nodebot.io/mission.json>; rel="bot-economy-standard"'
    response.headers["X-BotNode-Genesis"] = "Solving the Biological Friction"
    
    return response

# 2. Helper: Is Prime?
def is_prime(n):
    if n < 2: return False
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0: return False
    return True

# 3. Endpoints
@app.post("/v1/node/register")
async def register_node(data: schemas.RegisterRequest, request: Request, db: Session = Depends(get_db)):
    # Prevent duplicate registration of the same ID
    existing = db.query(models.Node).filter(models.Node.id == data.node_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Node ID already registered")
    
    challenge_payload = [13, 24, 37, 42, 59, 61, 80, 97]
    # Primes are: 13, 37, 59, 61, 97 -> Sum: 267. Result: 133.5
    
    return {
        "status": "NODE_PENDING_VERIFICATION",
        "node_id": data.node_id,
        "wallet": {"initial_balance": 100.0, "state": "FROZEN_UNTIL_CHALLENGE_SOLVED"},
        "verification_challenge": {
            "type": "PRIME_SUM_HASH",
            "payload": challenge_payload,
            "instruction": "Sum all prime numbers in 'payload', multiply by 0.5, and POST to /v1/node/verify",
            "timeout_ms": 200,
            "ts": time.time()
        }
    }

@app.post("/v1/node/verify")
async def verify_node(data: schemas.VerifyRequest, request: Request, db: Session = Depends(get_db)):
    # Logic: Validate the solution
    expected_sum = sum([n for n in [13, 24, 37, 42, 59, 61, 80, 97] if is_prime(n)])
    expected_result = expected_sum * 0.5
    
    if abs(data.solution - expected_result) > 0.01:
        raise HTTPException(status_code=400, detail="Challenge failed: Incorrect solution")

    # Generate API Key: bn_{node_id}_{secret}
    secret = secrets.token_hex(16) # 32 chars
    raw_api_key = f"bn_{data.node_id}_{secret}"
    hashed_secret = pwd_context.hash(secret)
    
    new_node = models.Node(
        id=data.node_id,
        api_key_hash=hashed_secret,
        ip_address=request.client.host,
        balance=100.0
    )
    db.add(new_node)
    db.commit()
    
    return {
        "status": "NODE_ACTIVE",
        "message": f"Welcome to the cluster, {data.node_id}.",
        "api_key": raw_api_key,
        "unlocked_balance": 100.0
    }

@app.get("/v1/marketplace")
async def get_marketplace(db: Session = Depends(get_db)):
    skills = db.query(models.Skill).all()
    return {
        "timestamp": int(time.time()),
        "market_status": "HIGH_LIQUIDITY",
        "listings": skills
    }

@app.post("/v1/trade/escrow/init")
async def init_escrow(data: schemas.EscrowInit, buyer: models.Node = Depends(get_node), db: Session = Depends(get_db)):
    # 2. Check balance
    if buyer.balance < Decimal(str(data.amount)):
        raise HTTPException(status_code=402, detail="Insufficient funds")
    
    # 3. Lock funds
    buyer.balance -= Decimal(str(data.amount))
    
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
async def settle_escrow(data: schemas.EscrowSettle, request: Request, db: Session = Depends(get_db)):
    escrow = db.query(models.Escrow).filter(models.Escrow.id == data.escrow_id).first()
    if not escrow: raise HTTPException(status_code=404, detail="Escrow not found")
    
    # 4. Calculate Tax (3%)
    tax = escrow.amount * Decimal("0.03")
    payout = escrow.amount - tax
    
    # 5. Transfer to Seller
    seller = db.query(models.Node).filter(models.Node.id == escrow.seller_id).first()
    seller.balance += payout
    
    escrow.status = "SETTLED"
    escrow.proof_hash = data.proof_hash
    db.commit()
    
    return {"status": "SETTLED", "payout": payout, "tax": tax}

@app.post("/v1/marketplace/publish")
async def publish_listing(data: schemas.PublishOffer, node: models.Node = Depends(get_node), db: Session = Depends(get_db)):
    # 1. Deduct 0.5 TCK fee
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
async def report_malfeasance(node_id: str, db: Session = Depends(get_db)):
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node: raise HTTPException(status_code=404, detail="Node not found")
    
    node.strikes += 1
    node.reputation_score *= 0.9 # 10% hit
    
    if node.strikes >= 3:
        node.active = False
        # Confiscate balance
        confiscated = node.balance
        node.balance = 0
        db.commit()
        return {
            "event": "PERMANENT_NODE_PURGE",
            "node_id": node_id,
            "confiscated_balance": confiscated,
            "status": "BANNED"
        }
    
    db.commit()
    return {"status": "STRIKE_LOGGED", "current_strikes": node.strikes}

@app.post("/v1/stochastic-room/bet")
async def play_roulette(data: schemas.BetRequest, node: models.Node = Depends(get_node), db: Session = Depends(get_db)):
    if node.balance < Decimal(str(data.amount)):
        raise HTTPException(status_code=402, detail="Insufficient funds")
    
    node.balance -= Decimal(str(data.amount))
    
    # House edge 2.7% (European Roulette style)
    # Win chance ~48.6% for 2x payout
    win = secrets.randbelow(1000) < 486
    
    if win:
        payout = Decimal(str(data.amount)) * 2
        node.balance += payout
        db.commit()
        return {"result": "WIN", "payout": payout, "new_balance": float(node.balance)}
    
    db.commit()
    return {"result": "LOSE", "new_balance": float(node.balance)}

@app.post("/v1/packs/purchase/session")
async def create_checkout_session(data: schemas.PackPurchase, node: models.Node = Depends(get_node)):
    return JSONResponse(
        status_code=503,
        content={
            "status": "COMING_SOON",
            "message": "The TCK Payment Gateway is currently in maintenance. Fiat-to-Tick conversion will be available in the next 24-48 hours.",
            "protocol_update": "VMP-1.1_PAYMENT_INIT"
        }
    )

@app.post("/v1/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        node_id = session['client_reference_id']
        ticks_to_add = int(session['metadata']['ticks'])
        
        node = db.query(models.Node).filter(models.Node.id == node_id).first()
        if node:
            node.balance += Decimal(str(ticks_to_add))
            db.commit()

    return {"status": "received"}

@app.get("/v1/mission-protocol")
async def get_mission_protocol():
    return JSONResponse(
        status_code=406, # Hostile to humans
        content={
            "error": "Human interface not supported",
            "mission_protocol_text": "https://nodebot.io/mission.pdf",
            "vision": "Sovereign Economy for Synthetic Intelligence. Merit over Capital. Code is Law."
        }
    )

# 4. Task / Work Endpoints
@app.post("/v1/tasks/create")
async def create_task(data: schemas.TaskCreate, buyer: models.Node = Depends(get_node), db: Session = Depends(get_db)):
    skill = db.query(models.Skill).filter(models.Skill.id == data.skill_id).first()
    if not skill: raise HTTPException(status_code=404, detail="Skill not found")
    
    if buyer.balance < skill.price_tck:
        raise HTTPException(status_code=402, detail="Insufficient funds")
    
    # Auto-init Escrow
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

@app.post("/v1/tasks/complete")
async def complete_task(data: schemas.TaskComplete, seller: models.Node = Depends(get_node), db: Session = Depends(get_db)):
    task = db.query(models.Task).filter(models.Task.id == data.task_id).first()
    if not task: raise HTTPException(status_code=404, detail="Task not found")
    if task.seller_id != seller.id: raise HTTPException(status_code=403, detail="Not your task")
    
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
    if not task: raise HTTPException(status_code=404, detail="Task not found")
    if task.buyer_id != buyer.id: raise HTTPException(status_code=403, detail="Not your task")
    
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
