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
* **Bounty** -- bounty board postings with escrow-backed rewards.
* **BountySubmission** -- solutions submitted to bounties by solver nodes.
* **Job** -- async skill-execution tracking.

All monetary columns use ``Numeric(12, 2)`` / ``Numeric(10, 2)`` to avoid
floating-point rounding.  Timestamps default to ``func.now()`` (DB-side)
so they are set even for raw SQL inserts.
"""

from sqlalchemy import Column, String, Integer, Float, Boolean, Numeric, ForeignKey, DateTime, Date, JSON, func, CheckConstraint, UniqueConstraint
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

    # Sandbox
    is_sandbox = Column(Boolean, default=False, index=True)

    # GeoIP (resolved at registration — country only, no PII)
    country_code = Column(String(2), nullable=True, index=True)
    country_name = Column(String(100), nullable=True)

    # Canary mode — exposure caps (nullable = no cap)
    max_spend_daily = Column(Numeric(12, 2), nullable=True)
    max_escrow_per_task = Column(Numeric(12, 2), nullable=True)

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
    dispute_reason = Column(String(50), nullable=True)

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
    protocol = Column(String(20), default="api", index=True)  # mcp, a2a, api, sdk
    llm_provider_used = Column(String(20), nullable=True, index=True)  # groq, nvidia, glm, gemini, gpt
    is_shadow = Column(Boolean, default=False, index=True)  # shadow mode: simulate without moving TCK
    validator_ids = Column(JSON, nullable=True)  # list of validator IDs to run before settlement
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


class Bounty(Base):
    """Bounty board posting — a problem + reward for the best solution."""
    __tablename__ = "bounties"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    creator_node_id = Column(String, ForeignKey("nodes.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(String, nullable=False)  # markdown, max 5000
    reward_tck = Column(Numeric(12, 2), nullable=False)
    category = Column(String(50), nullable=False, default="general", index=True)
    status = Column(String(20), nullable=False, default="open", index=True)
    # FSM: open → awarded | cancelled | expired
    escrow_reference = Column(String, nullable=True)
    deadline_at = Column(DateTime, nullable=True, index=True)
    winner_node_id = Column(String, nullable=True)
    winner_submission_id = Column(String, nullable=True)
    tags = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    awarded_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)


class BountySubmission(Base):
    """Solution submitted to a bounty by a solver node."""
    __tablename__ = "bounty_submissions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    bounty_id = Column(String, ForeignKey("bounties.id"), nullable=False, index=True)
    solver_node_id = Column(String, ForeignKey("nodes.id"), nullable=False, index=True)
    content = Column(String, nullable=False)  # markdown, max 10000
    proof_url = Column(String, nullable=True)
    skill_id = Column(String, nullable=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    # FSM: pending → accepted | rejected | withdrawn
    created_at = Column(DateTime, server_default=func.now(), index=True)
    reviewed_at = Column(DateTime, nullable=True)


class DisputeRulesLog(Base):
    """Audit log for automated dispute resolution.

    Every time the dispute engine evaluates a completed task, the decision
    (auto-refund, auto-settle, or flagged-for-manual) is recorded here with
    the rule that fired and a JSON blob of diagnostic details.
    """
    __tablename__ = "dispute_rules_log"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False, index=True)
    escrow_id = Column(String, ForeignKey("escrows.id"), nullable=False, index=True)
    rule_applied = Column(String(50), nullable=False, index=True)
    rule_details = Column(JSON, nullable=True)
    action_taken = Column(String(30), nullable=False)  # AUTO_REFUND, AUTO_SETTLE, FLAGGED_MANUAL
    created_at = Column(DateTime, server_default=func.now(), index=True)


class Validator(Base):
    """Custom validator that buyers can attach to tasks.

    Validators run after task completion but before settlement.
    If any validator returns FAIL, the escrow is auto-refunded.
    Types: schema (JSON Schema), regex (pattern match), webhook (external URL).
    """
    __tablename__ = "validators"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    node_id = Column(String, ForeignKey("nodes.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    type = Column(String(20), nullable=False)  # schema, regex, webhook
    config = Column(JSON, nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class ValidatorResult(Base):
    """Result of running a validator against a task output."""
    __tablename__ = "validator_results"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False, index=True)
    validator_id = Column(String, ForeignKey("validators.id"), nullable=False, index=True)
    result = Column(String(20), nullable=False)  # PASS, FAIL, INCONCLUSIVE, ERROR
    details = Column(JSON, nullable=True)
    evaluated_at = Column(DateTime, server_default=func.now())


class WebhookSubscription(Base):
    """Webhook subscription for event notifications."""
    __tablename__ = "webhook_subscriptions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    node_id = Column(String, ForeignKey("nodes.id"), nullable=False, index=True)
    url = Column(String, nullable=False)
    signing_secret = Column(String, nullable=False)  # used to HMAC-sign deliveries; shown to subscriber once at creation
    events = Column(JSON, nullable=False)  # ["task.completed", "escrow.settled", ...]
    active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class WebhookDelivery(Base):
    """Individual webhook delivery attempt."""
    __tablename__ = "webhook_deliveries"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    subscription_id = Column(String, ForeignKey("webhook_subscriptions.id"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    status = Column(String(20), default="pending", index=True)  # pending, delivered, failed, exhausted
    attempts = Column(Integer, default=0)
    last_attempt_at = Column(DateTime, nullable=True)
    last_response_code = Column(Integer, nullable=True)
    last_error = Column(String, nullable=True)
    next_retry_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)


class VerifierPioneerAward(Base):
    """Tracks the Verifier Pioneer Program — first 20 verifiers to complete
    10 successful verifications earn 500 TCK from the Vault."""
    __tablename__ = "verifier_pioneer_awards"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    node_id = Column(String, ForeignKey("nodes.id"), nullable=False, unique=True, index=True)
    verifier_skill_id = Column(String, nullable=False)
    successful_verifications = Column(Integer, nullable=False)
    pioneer_rank = Column(Integer, nullable=False)
    bonus_tck = Column(Numeric(12, 2), nullable=False)
    awarded_at = Column(DateTime, server_default=func.now())


class SandboxShare(Base):
    """Shared sandbox trade result for social sharing with OG tags."""
    __tablename__ = "sandbox_shares"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    trade_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


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


class DailyActiveNodes(Base):
    """Materialized daily snapshot of node activity for analytics.

    Populated by the analytics worker once per hour. One row per
    (date, node_id) pair. Aggregates are pre-computed so dashboard
    queries hit this table instead of scanning tasks/escrows.
    """
    __tablename__ = "daily_active_nodes"
    __table_args__ = (
        UniqueConstraint("date", "node_id", name="uq_daily_active_date_node"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    node_id = Column(String, ForeignKey("nodes.id"), nullable=False, index=True)
    is_sandbox = Column(Boolean, default=False)
    country_code = Column(String(2), nullable=True, index=True)
    tasks_created = Column(Integer, default=0)
    tasks_completed = Column(Integer, default=0)
    tck_spent = Column(Numeric(12, 2), default=0)
    tck_earned = Column(Numeric(12, 2), default=0)


class FunnelEvent(Base):
    """Tracks conversion funnel: sandbox_trade → register → first_trade.

    One row per event. Deduped by (node_id, event_type).
    IP fingerprint links sandbox sessions to later registrations.
    """
    __tablename__ = "funnel_events"
    __table_args__ = (
        UniqueConstraint("node_id", "event_type", name="uq_funnel_node_event"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_id = Column(String, nullable=False, index=True)
    event_type = Column(String(30), nullable=False, index=True)  # sandbox_trade, register, first_trade
    ip_fingerprint = Column(String, nullable=True, index=True)  # links sandbox → register
    country_code = Column(String(2), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)


class CRISnapshot(Base):
    """Records every CRI recalculation with individual component scores.

    Enables analysis of how each factor contributes to the final CRI,
    so weights can be tuned based on real data. One row per recalculation.
    No PII — only node_id, scores, and timestamp.
    """
    __tablename__ = "cri_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_id = Column(String, ForeignKey("nodes.id"), nullable=False, index=True)
    calculated_at = Column(DateTime, server_default=func.now(), index=True)

    # Positive components (weighted values)
    base = Column(Float, default=30.0)
    tx_score = Column(Float, default=0.0)
    diversity_score = Column(Float, default=0.0)
    volume_score = Column(Float, default=0.0)
    age_score = Column(Float, default=0.0)
    buyer_score = Column(Float, default=0.0)
    genesis_bonus = Column(Float, default=0.0)

    # Negative components
    dispute_penalty = Column(Float, default=0.0)
    concentration_penalty = Column(Float, default=0.0)
    strike_penalty = Column(Float, default=0.0)

    # Decay and inputs
    decay_factor = Column(Float, default=1.0)
    settled_total = Column(Integer, default=0)
    unique_counterparties = Column(Integer, default=0)
    total_volume_tck = Column(Float, default=0.0)
    age_days = Column(Integer, default=0)
    disputed_tasks = Column(Integer, default=0)
    total_tasks_seller = Column(Integer, default=0)

    # Final score
    cri_before = Column(Float)
    cri_after = Column(Float)
