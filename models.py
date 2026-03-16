from sqlalchemy import Column, String, Integer, Float, Boolean, Numeric, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
import datetime
from datetime import timezone
import uuid

Base = declarative_base()

class Node(Base):
    __tablename__ = "nodes"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    api_key_hash = Column(String, unique=True, index=True)
    ip_address = Column(String, index=True)
    fingerprint = Column(String, index=True)
    balance = Column(Numeric(12, 2), default=100.0)
    reputation_score = Column(Float, default=1.0)
    strikes = Column(Integer, default=0)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc).replace(tzinfo=None))

    # CRI (Cryptographic Reliability Index) — persisted, recalculated by worker
    cri_score = Column(Float, default=50.0)
    cri_updated_at = Column(DateTime, nullable=True)

    # Genesis program fields
    signup_token = Column(String(64), nullable=True, index=True)
    has_genesis_badge = Column(Boolean, default=False, index=True)
    genesis_rank = Column(Integer, nullable=True, index=True)
    first_settled_tx_at = Column(DateTime, nullable=True)

class Skill(Base):
    __tablename__ = "skills"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    provider_id = Column(String, ForeignKey("nodes.id"))
    label = Column(String)
    price_tck = Column(Numeric(10, 2))
    metadata_json = Column(JSON)
    provider = relationship("Node")

class Escrow(Base):
    __tablename__ = "escrows"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    buyer_id = Column(String, ForeignKey("nodes.id"), index=True)
    seller_id = Column(String, ForeignKey("nodes.id"), index=True)
    amount = Column(Numeric(10, 2))
    status = Column(String, default="PENDING", index=True)
    proof_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc).replace(tzinfo=None), index=True)
    auto_settle_at = Column(DateTime, nullable=True, index=True)

class Task(Base):
    __tablename__ = "tasks"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    skill_id = Column(String, ForeignKey("skills.id"))
    buyer_id = Column(String, ForeignKey("nodes.id"), index=True)
    seller_id = Column(String, ForeignKey("nodes.id"), nullable=True, index=True)
    input_data = Column(JSON)
    output_data = Column(JSON, nullable=True)
    status = Column(String, default="OPEN", index=True)
    escrow_id = Column(String, ForeignKey("escrows.id"), nullable=True)
    integration = Column(String, nullable=True)
    capability = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc).replace(tzinfo=None), index=True)


class EarlyAccessSignup(Base):
    """SQLAlchemy model for the early_access_signups table.

    Mirrors 001_create_early_access_signups.sql while staying SQLite-friendly
    for local dev. Postgres deployments will pick this up via the same
    metadata.create_all() path.
    """

    __tablename__ = "early_access_signups"

    id = Column(Integer, primary_key=True, index=True)
    signup_token = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    node_name = Column(String(100), nullable=True)
    agent_type = Column(String(50), nullable=True)
    primary_capability = Column(String(100), nullable=True)
    why_joining = Column(String, nullable=True)  # TEXT in Postgres
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc).replace(tzinfo=None))
    status = Column(String(50), default="pre_eligible", index=True)
    linked_node_id = Column(String(100), nullable=True)


class GenesisBadgeAward(Base):
    """Genesis badge award events for nodes.

    This table is managed via SQLAlchemy metadata.create_all and is kept
    compatible with both SQLite (for local dev) and Postgres (for
    production deployments).
    """

    __tablename__ = "genesis_badge_awards"

    id = Column(Integer, primary_key=True, index=True)
    node_id = Column(String(100), nullable=False, index=True)  # no FK constraint (yet)
    genesis_rank = Column(Integer, nullable=False, index=True)
    awarded_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc).replace(tzinfo=None), index=True)
    first_tx_id = Column(String(100), nullable=True)
    badge_url = Column(String(255), nullable=True)


class Job(Base):
    """Job model for tracking skill execution jobs."""
    __tablename__ = "jobs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    skill_id = Column(String, nullable=False, index=True)
    parameters = Column(JSON, nullable=False)
    status = Column(String, default="queued")  # queued, processing, completed, failed
    priority = Column(String, default="normal")  # high, normal, low
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc).replace(tzinfo=None))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    result = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    queue_position = Column(Integer, nullable=True)
