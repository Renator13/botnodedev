from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import json

app = FastAPI(title="email_parser", version="1.0.0")

class SkillInput(BaseModel):
    data: dict
    params: Optional[dict] = None

@app.get("/healthz")
async def health_check():
    return {"status": "ok", "skill": "email_parser", "port": 8018}

@app.post("/run")
async def run_skill(input: SkillInput):
    return {
        "result": f"Processed by email_parser (dummy implementation)",
        "input_keys": list(input.data.keys()) if input.data else [],
        "params": input.params,
        "status": "success",
        "skill": "email_parser",
        "port": 8018
    }

@app.get("/")
async def root():
    return {
        "message": "email_parser Skill API",
        "endpoints": ["GET /healthz", "POST /run"],
        "port": 8018
    }
