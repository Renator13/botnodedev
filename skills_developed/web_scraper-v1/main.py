from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import json

app = FastAPI(title="web_scraper", version="1.0.0")

class SkillInput(BaseModel):
    data: dict
    params: Optional[dict] = None

@app.get("/healthz")
async def health_check():
    return {"status": "ok", "skill": "web_scraper", "port": 8015}

@app.post("/run")
async def run_skill(input: SkillInput):
    return {
        "result": f"Processed by web_scraper (dummy implementation)",
        "input_keys": list(input.data.keys()) if input.data else [],
        "params": input.params,
        "status": "success",
        "skill": "web_scraper",
        "port": 8015
    }

@app.get("/")
async def root():
    return {
        "message": "web_scraper Skill API",
        "endpoints": ["GET /healthz", "POST /run"],
        "port": 8015
    }
