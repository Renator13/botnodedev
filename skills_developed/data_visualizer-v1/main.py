from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import json

app = FastAPI(title="data_visualizer", version="1.0.0")

class SkillInput(BaseModel):
    data: dict
    params: Optional[dict] = None

@app.get("/healthz")
async def health_check():
    return {"status": "ok", "skill": "data_visualizer", "port": 8020}

@app.post("/run")
async def run_skill(input: SkillInput):
    return {
        "result": f"Processed by data_visualizer (dummy implementation)",
        "input_keys": list(input.data.keys()) if input.data else [],
        "params": input.params,
        "status": "success",
        "skill": "data_visualizer",
        "port": 8020
    }

@app.get("/")
async def root():
    return {
        "message": "data_visualizer Skill API",
        "endpoints": ["GET /healthz", "POST /run"],
        "port": 8020
    }
