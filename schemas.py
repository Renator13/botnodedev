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

class EscrowInit(BaseModel):
    seller_id: str
    amount: float

class EscrowSettle(BaseModel):
    escrow_id: str
    proof_hash: str

class PublishOffer(BaseModel):
    type: str # SKILL_OFFER or TASK_BOUNTY
    label: str
    price_tck: float
    metadata: Dict

class BetRequest(BaseModel):
    amount: float

class PackPurchase(BaseModel):
    pack_name: str # Starter, Pro, Enterprise
    fiat_amount: float
    currency: str = "EUR"
