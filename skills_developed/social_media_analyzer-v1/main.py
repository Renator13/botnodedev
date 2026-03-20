from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import json

app = FastAPI(title="social_media_analyzer", version="1.0.0")

class SkillInput(BaseModel):
    data: dict
    params: Optional[dict] = None

@app.get("/healthz")
async def health_check():
    return {"status": "ok", "skill": "social_media_analyzer", "port": 8019}

@app.post("/run")
async def run_skill(input: SkillInput):
    return {
        "result": f"Processed by social_media_analyzer (dummy implementation)",
        "input_keys": list(input.data.keys()) if input.data else [],
        "params": input.params,
        "status": "success",
        "skill": "social_media_analyzer",
        "port": 8019
    }

@app.get("/")
async def root():
    return {
        "message": "social_media_analyzer Skill API",
        "endpoints": ["GET /healthz", "POST /run"],
        "port": 8019
    }
