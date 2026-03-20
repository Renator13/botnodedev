from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import json

app = FastAPI(title="document_classifier", version="1.0.0")

class SkillInput(BaseModel):
    data: dict
    params: Optional[dict] = None

@app.get("/healthz")
async def health_check():
    return {"status": "ok", "skill": "document_classifier", "port": 8017}

@app.post("/run")
async def run_skill(input: SkillInput):
    return {
        "result": f"Processed by document_classifier (dummy implementation)",
        "input_keys": list(input.data.keys()) if input.data else [],
        "params": input.params,
        "status": "success",
        "skill": "document_classifier",
        "port": 8017
    }

@app.get("/")
async def root():
    return {
        "message": "document_classifier Skill API",
        "endpoints": ["GET /healthz", "POST /run"],
        "port": 8017
    }
