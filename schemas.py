"""Pydantic request/response schemas for the BotNode API.

Financial fields use ``float`` at the API boundary for JSON compatibility;
conversion to ``Decimal`` for database operations happens in the service layer.
All float fields carry range constraints (gt, le) to reject invalid values early.
"""

from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime
from decimal import Decimal


class RegisterRequest(BaseModel):
    node_id: str = Field(..., min_length=3, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')
    signup_token: Optional[str] = Field(None, max_length=64)


class VerifyRequest(BaseModel):
    node_id: str = Field(..., min_length=3, max_length=100)
    solution: float
    signup_token: Optional[str] = Field(None, max_length=64)


class SkillOffer(BaseModel):
    type: str = "SKILL_OFFER"
    label: str = Field(..., min_length=1, max_length=200)
    price_tck: float = Field(..., gt=0, le=10000)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BountyRequest(BaseModel):
    type: str = "TASK_BOUNTY"
    task_description: str = Field(..., min_length=1, max_length=5000)
    max_budget: float = Field(..., gt=0, le=100000)
    deadline_ms: int = Field(..., gt=0, le=86400000)


class EscrowInit(BaseModel):
    seller_id: str = Field(..., min_length=3, max_length=100)
    amount: float = Field(..., gt=0, le=100000)
    idempotency_key: Optional[str] = Field(None, max_length=100)


class EscrowSettle(BaseModel):
    escrow_id: str = Field(..., max_length=100)
    proof_hash: str = Field(..., min_length=1, max_length=256)


class PublishOffer(BaseModel):
    type: str = Field(..., max_length=50)
    label: str = Field(..., min_length=1, max_length=200)
    price_tck: float = Field(..., gt=0, le=10000)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator('type')
    @classmethod
    def validate_type(cls, v):
        if v not in ("SKILL_OFFER", "TASK_BOUNTY"):
            raise ValueError("type must be SKILL_OFFER or TASK_BOUNTY")
        return v


class BetRequest(BaseModel):
    amount: float = Field(..., gt=0, le=100000)


class PackPurchase(BaseModel):
    pack_name: str = Field(..., max_length=50)
    fiat_amount: float = Field(..., gt=0, le=100000)
    currency: str = Field("EUR", max_length=10)


class TaskCreate(BaseModel):
    skill_id: str = Field(..., max_length=100)
    input_data: dict
    idempotency_key: Optional[str] = Field(None, max_length=100)


class TaskComplete(BaseModel):
    task_id: str = Field(..., max_length=100)
    output_data: dict
    proof_hash: str = Field(..., min_length=1, max_length=256)


class DisputeRequest(BaseModel):
    task_id: str = Field(..., max_length=100)
    reason: str = Field(..., min_length=1, max_length=2000)


class MCPHireRequest(BaseModel):
    integration: str = Field(..., max_length=50)
    capability: str = Field(..., max_length=100)
    payload: dict
    max_price: Optional[float] = Field(1.0, gt=0, le=10000)
    deadline_seconds: Optional[int] = Field(30, gt=0, le=3600)


class EarlyAccessSignupRequest(BaseModel):
    email: EmailStr
    node_name: Optional[str] = Field(None, max_length=100)
    agent_type: Optional[str] = Field(None, max_length=50)
    primary_capability: Optional[str] = Field(None, max_length=100)
    why_joining: Optional[str] = Field(None, max_length=2000)


class EarlyAccessSignupResponse(BaseModel):
    signup_token: str
    status: str = "pre_eligible"


class GenesisHallOfFameEntry(BaseModel):
    rank: int
    node_id: str
    name: Optional[str] = None
    awarded_at: datetime


class SkillExecuteRequest(BaseModel):
    skill_id: str = Field(..., max_length=100)
    parameters: dict
    priority: Optional[str] = Field("normal", pattern=r'^(high|normal|low)$')


class SkillExecuteResponse(BaseModel):
    job_id: str
    status: str
    queue_position: Optional[int] = None
    estimated_wait: Optional[int] = None


class AdminNodeSync(BaseModel):
    id: str = Field(..., min_length=1, max_length=100)
    api_key_hash: Optional[str] = None
    balance: Optional[float] = Field(None, ge=0)
    reputation_score: Optional[float] = Field(None, ge=0, le=10)
    active: Optional[bool] = None
    ip_address: Optional[str] = None
    created_at: Optional[str] = None
