from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import json

app = FastAPI(title="lead_enricher", version="1.0.0")

class SkillInput(BaseModel):
    data: dict
    params: Optional[dict] = None

@app.get("/healthz")
async def health_check():
    return {"status": "ok", "skill": "lead_enricher", "port": 8012}

@app.post("/run")
async def run_skill(input: SkillInput):
    return {
        "result": f"Processed by lead_enricher (dummy implementation)",
        "input_keys": list(input.data.keys()) if input.data else [],
        "params": input.params,
        "status": "success",
        "skill": "lead_enricher",
        "port": 8012
    }

@app.get("/")
async def root():
    return {
        "message": "lead_enricher Skill API",
        "endpoints": ["GET /healthz", "POST /run"],
        "port": 8012
    }
