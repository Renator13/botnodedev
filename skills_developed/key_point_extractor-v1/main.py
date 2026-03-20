from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import json

app = FastAPI(title="key_point_extractor", version="1.0.0")

class SkillInput(BaseModel):
    data: dict
    params: Optional[dict] = None

@app.get("/healthz")
async def health_check():
    return {"status": "ok", "skill": "key_point_extractor", "port": 8011}

@app.post("/run")
async def run_skill(input: SkillInput):
    return {
        "result": f"Processed by key_point_extractor (dummy implementation)",
        "input_keys": list(input.data.keys()) if input.data else [],
        "params": input.params,
        "status": "success",
        "skill": "key_point_extractor",
        "port": 8011
    }

@app.get("/")
async def root():
    return {
        "message": "key_point_extractor Skill API",
        "endpoints": ["GET /healthz", "POST /run"],
        "port": 8011
    }
