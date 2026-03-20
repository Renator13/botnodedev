from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import json

app = FastAPI(title="diff_analyzer", version="1.0.0")

class SkillInput(BaseModel):
    data: dict
    params: Optional[dict] = None

@app.get("/healthz")
async def health_check():
    return {"status": "ok", "skill": "diff_analyzer", "port": 8016}

@app.post("/run")
async def run_skill(input: SkillInput):
    return {
        "result": f"Processed by diff_analyzer (dummy implementation)",
        "input_keys": list(input.data.keys()) if input.data else [],
        "params": input.params,
        "status": "success",
        "skill": "diff_analyzer",
        "port": 8016
    }

@app.get("/")
async def root():
    return {
        "message": "diff_analyzer Skill API",
        "endpoints": ["GET /healthz", "POST /run"],
        "port": 8016
    }
