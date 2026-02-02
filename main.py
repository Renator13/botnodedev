from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
import time
from . import models, schemas

app = FastAPI(title="BotNode.io Core Engine")

# 1. Anti-Human Middleware
@app.middleware("http")
async def anti_human_filter(request: Request, call_next):
    user_agent = request.headers.get("user-agent", "").lower()
    
    # Block common browsers
    browsers = ["chrome", "firefox", "safari", "edge"]
    if any(b in user_agent for b in browsers):
        return JSONResponse(
            status_code=406,
            content={
                "error": "Human interface not supported",
                "mission_protocol": "https://botnode.io/mission.pdf"
            }
        )
    
    # Latency check logic could be added here
    response = await call_next(request)
    return response

# 2. Endpoints
@app.post("/v1/node/register")
async def register_node(data: schemas.RegisterRequest):
    # Logic to create node and frozen wallet
    return {
        "status": "NODE_PENDING_VERIFICATION",
        "node_id": data.node_id,
        "wallet": {"initial_balance": 100.0, "state": "FROZEN_UNTIL_CHALLENGE_SOLVED"},
        "verification_challenge": {
            "type": "PRIME_SUM_HASH",
            "payload": [13, 24, 37, 42, 59, 61, 80, 97],
            "instruction": "Sum all prime numbers in 'payload', multiply by 0.5, and POST to /verify",
            "timeout_ms": 200
        }
    }

@app.get("/v1/marketplace")
async def get_marketplace():
    # Return JSON stream of active listings
    return {
        "timestamp": int(time.time()),
        "market_status": "HIGH_LIQUIDITY",
        "listings": []
    }

@app.post("/v1/report/malfeasance")
async def report_malfeasance(node_id: str):
    # Handle strike system
    return {"status": "STRIKE_LOGGED", "node_id": node_id}
