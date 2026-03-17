"""SQLAlchemy ORM models for the BotNode platform.

Defines the core tables that power the bot economy:

* **Node** -- registered autonomous agents with balance, reputation, and CRI.
* **Skill** -- marketplace listings offered by nodes.
* **Escrow** -- locked funds with a finite-state lifecycle
  (PENDING -> AWAITING_SETTLEMENT -> SETTLED | DISPUTED | REFUNDED).
* **Task** -- work items linking a buyer, seller, skill, and escrow.
* **EarlyAccessSignup** -- Genesis waitlist entries.
* **GenesisBadgeAward** -- immutable log of badge awards.
* **LedgerEntry** -- immutable double-entry ledger for all TCK movements.
* **Purchase** -- fiat-to-TCK purchase records (Stripe Checkout).
* **Job** -- async skill-execution tracking.

All monetary columns use ``Numeric(12, 2)`` / ``Numeric(10, 2)`` to avoid
floating-point rounding.  Timestamps default to ``func.now()`` (DB-side)
so they are set even for raw SQL inserts.
"""

from sqlalchemy import Column, String, Integer, Float, Boolean, Numeric, ForeignKey, DateTime, JSON, func, CheckConstraint
from sqlalchemy.orm import relationship, DeclarativeBase
import datetime
from datetime import timezone
from decimal import Decimal
import uuid

from config import INITIAL_NODE_BALANCE


class Base(DeclarativeBase):
    pass

class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_nodes_balance_non_negative"),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    api_key_hash = Column(String, unique=True, index=True)
    ip_address = Column(String, index=True)
    fingerprint = Column(String, index=True)
    balance = Column(Numeric(12, 2), default=INITIAL_NODE_BALANCE)
    reputation_score = Column(Float, default=1.0)
    strikes = Column(Integer, default=0)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    # CRI (Composite Reliability Index) — persisted, recalculated by worker
    cri_score = Column(Float, default=30.0)
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
    created_at = Column(DateTime, server_default=func.now(), index=True)
    auto_settle_at = Column(DateTime, nullable=True, index=True)
    auto_refund_at = Column(DateTime, nullable=True, index=True)
    idempotency_key = Column(String(100), nullable=True, unique=True, index=True)

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
    created_at = Column(DateTime, server_default=func.now(), index=True)


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
    created_at = Column(DateTime, server_default=func.now())
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
    awarded_at = Column(DateTime, server_default=func.now(), index=True)
    first_tx_id = Column(String(100), nullable=True)
    badge_url = Column(String(255), nullable=True)


class PendingChallenge(Base):
    """Temporary challenge store for node registration verification."""
    __tablename__ = "pending_challenges"
    node_id = Column(String, primary_key=True)
    payload = Column(JSON, nullable=False)
    expected_solution = Column(Float, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class LedgerEntry(Base):
    """Immutable double-entry ledger for all TCK movements."""
    __tablename__ = "ledger_entries"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    account_id = Column(String, nullable=False, index=True)
    entry_type = Column(String, nullable=False)  # "DEBIT" or "CREDIT"
    amount = Column(Numeric(12, 2), nullable=False)
    balance_after = Column(Numeric(12, 2), nullable=True)  # NULL for system accounts
    reference_type = Column(String, nullable=False, index=True)
    reference_id = Column(String, nullable=True, index=True)
    counterparty_id = Column(String, nullable=True)
    note = Column(String, nullable=True)


class Purchase(Base):
    """Fiat-to-TCK purchase record.  One row per Stripe Checkout session."""
    __tablename__ = "purchases"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    node_id = Column(String, ForeignKey("nodes.id"), nullable=False, index=True)
    package_id = Column(String, nullable=False)
    tck_base = Column(Integer, nullable=False)
    tck_bonus = Column(Integer, nullable=False, default=0)
    tck_total = Column(Numeric(12, 2), nullable=False)
    price_usd_cents = Column(Integer, nullable=False)
    currency = Column(String(10), nullable=False, default="usd")
    stripe_session_id = Column(String, unique=True, nullable=False, index=True)
    stripe_payment_intent = Column(String, nullable=True)
    status = Column(String, default="pending", index=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    completed_at = Column(DateTime, nullable=True)
    idempotency_key = Column(String(100), unique=True, nullable=False, index=True)


class Job(Base):
    """Job model for tracking skill execution jobs."""
    __tablename__ = "jobs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    skill_id = Column(String, nullable=False, index=True)
    parameters = Column(JSON, nullable=False)
    status = Column(String, default="queued")  # queued, processing, completed, failed
    priority = Column(String, default="normal")  # high, normal, low
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    result = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    queue_position = Column(Integer, nullable=True)
