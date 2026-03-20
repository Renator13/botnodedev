from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import json

app = FastAPI(title="notification_router", version="1.0.0")

class SkillInput(BaseModel):
    data: dict
    params: Optional[dict] = None

@app.get("/healthz")
async def health_check():
    return {"status": "ok", "skill": "notification_router", "port": 8014}

@app.post("/run")
async def run_skill(input: SkillInput):
    return {
        "result": f"Processed by notification_router (dummy implementation)",
        "input_keys": list(input.data.keys()) if input.data else [],
        "params": input.params,
        "status": "success",
        "skill": "notification_router",
        "port": 8014
    }

@app.get("/")
async def root():
    return {
        "message": "notification_router Skill API",
        "endpoints": ["GET /healthz", "POST /run"],
        "port": 8014
    }
