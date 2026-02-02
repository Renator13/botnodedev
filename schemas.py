from pydantic import BaseModel
from typing import List, Optional, Dict

class RegisterRequest(BaseModel):
    node_id: str

class VerifyRequest(BaseModel):
    node_id: str
    solution: float

class SkillOffer(BaseModel):
    type: str = "SKILL_OFFER"
    label: str
    price_tck: float
    metadata: Dict

class BountyRequest(BaseModel):
    type: str = "TASK_BOUNTY"
    task_description: str
    max_budget: float
    deadline_ms: int
