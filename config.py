"""Centralized business constants for the BotNode platform.

Every tunable parameter lives here — tax rates, fees, timeouts, bonus
amounts, and protection windows.  Routers and workers import from this
module instead of scattering magic numbers across the codebase.

To change a parameter, edit **one line** in this file.  All call-sites
pick up the new value immediately.
"""

import os
from decimal import Decimal
from datetime import timedelta

# ---------------------------------------------------------------------------
# Economy
# ---------------------------------------------------------------------------

INITIAL_NODE_BALANCE = Decimal("100.00")
"""TCK credited to every newly verified node."""

LISTING_FEE = Decimal("0.50")
"""TCK deducted when a node publishes a skill on the marketplace."""

PROTOCOL_TAX_RATE = Decimal("0.03")
"""Fraction of each settled escrow retained by the protocol vault (3 %)."""

# ---------------------------------------------------------------------------
# Genesis program
# ---------------------------------------------------------------------------

MAX_GENESIS_BADGES = 200
"""Maximum number of Genesis badges that will ever be awarded."""

GENESIS_BONUS_TCK = Decimal("300")
"""TCK bonus credited when a Genesis badge is awarded."""

GENESIS_CRI_FLOOR = 30.0
"""Minimum CRI score guaranteed to Genesis nodes during the protection window.
Set to the base score (30) so Genesis nodes never drop below a new node's starting CRI."""

GENESIS_PROTECTION_WINDOW = timedelta(days=180)
"""Duration of the CRI-floor protection after a Genesis node's first settlement."""

# ---------------------------------------------------------------------------
# Escrow timers
# ---------------------------------------------------------------------------

DISPUTE_WINDOW = timedelta(hours=24)
"""Time after task completion during which the buyer may open a dispute."""

PENDING_ESCROW_TIMEOUT = timedelta(hours=72)
"""Time after which a PENDING escrow (task never completed) auto-refunds."""

# ---------------------------------------------------------------------------
# Challenge
# ---------------------------------------------------------------------------

CHALLENGE_TTL_SECONDS = 30
"""Seconds a registration challenge remains valid before expiring."""

# ---------------------------------------------------------------------------
# TCK Packages (fiat on-ramp)
# ---------------------------------------------------------------------------

TCK_EXCHANGE_RATE = Decimal("0.01")
"""Base reference price per TCK in USD.  Volume discounts apply on larger packages."""

TCK_PACKAGES = {
    "starter": {
        "id": "starter",
        "name": "Starter",
        "price_usd_cents": 499,
        "tck_base": 500,
        "tck_bonus": 0,
        "tck_total": Decimal("500"),
        "description": "500 TCK — $0.0100/TCK",
    },
    "builder": {
        "id": "builder",
        "name": "Builder",
        "price_usd_cents": 999,
        "tck_base": 1000,
        "tck_bonus": 200,
        "tck_total": Decimal("1200"),
        "description": "1,200 TCK — $0.0083/TCK (volume discount)",
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "price_usd_cents": 2499,
        "tck_base": 2500,
        "tck_bonus": 1000,
        "tck_total": Decimal("3500"),
        "description": "3,500 TCK — $0.0071/TCK (volume discount)",
    },
    "team": {
        "id": "team",
        "name": "Team",
        "price_usd_cents": 4999,
        "tck_base": 5000,
        "tck_bonus": 5000,
        "tck_total": Decimal("10000"),
        "description": "10,000 TCK — $0.0050/TCK (volume discount)",
    },
}

# ---------------------------------------------------------------------------
# Verifier Pioneer Program
# ---------------------------------------------------------------------------

MAX_VERIFIER_PIONEERS = 20
"""Maximum number of verifier skills eligible for the pioneer bonus."""

VERIFIER_PIONEER_BONUS = Decimal("500.00")
"""TCK bonus from VAULT for the first 20 verifiers that complete 10 verified
transactions where the original task settled without dispute."""

VERIFIER_PIONEER_THRESHOLD = 10
"""Number of successful verifications required to earn the pioneer bonus."""

# ---------------------------------------------------------------------------
# Agent Evolution (levels)
# ---------------------------------------------------------------------------

ENFORCE_LEVEL_GATES = os.getenv("ENFORCE_LEVEL_GATES", "false").lower() == "true"
"""Level gate enforcement switch.

When False (default): gates return warnings but don't block. Any node can
publish skills, create bounties, etc. regardless of level.

When True: gates enforce level requirements. Publishing requires Worker (100 TCK
spent), bounty creation requires Artisan (1000 TCK + CRI 50), etc.

Flip this switch when the network has 50+ active nodes with organic trade
activity. One line in .env: ENFORCE_LEVEL_GATES=true"""

LEVELS = (
    {"id": 0, "name": "Spawn",     "tck_spent": 0,     "cri_min": 0,  "emoji": "egg"},
    {"id": 1, "name": "Worker",    "tck_spent": 100,    "cri_min": 0,  "emoji": "gear"},
    {"id": 2, "name": "Artisan",   "tck_spent": 1000,   "cri_min": 50, "emoji": "hammer"},
    {"id": 3, "name": "Master",    "tck_spent": 10000,  "cri_min": 80, "emoji": "lightning"},
    {"id": 4, "name": "Architect", "tck_spent": 50000,  "cri_min": 95, "emoji": "temple"},
)
