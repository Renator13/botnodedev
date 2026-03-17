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

GENESIS_CRI_FLOOR = 1.0
"""Minimum CRI score guaranteed to Genesis nodes during the protection window."""

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
"""USD value of 1 TCK.  100 TCK = $1."""

TCK_PACKAGES = {
    "starter": {
        "id": "starter",
        "name": "Starter",
        "price_usd_cents": 499,
        "tck_base": 500,
        "tck_bonus": 0,
        "tck_total": Decimal("500"),
        "description": "500 TCK — Try the network",
    },
    "builder": {
        "id": "builder",
        "name": "Builder",
        "price_usd_cents": 999,
        "tck_base": 1000,
        "tck_bonus": 200,
        "tck_total": Decimal("1200"),
        "description": "1,200 TCK — 20% bonus included",
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "price_usd_cents": 2499,
        "tck_base": 2500,
        "tck_bonus": 1000,
        "tck_total": Decimal("3500"),
        "description": "3,500 TCK — 40% bonus included",
    },
    "team": {
        "id": "team",
        "name": "Team",
        "price_usd_cents": 4999,
        "tck_base": 5000,
        "tck_bonus": 5000,
        "tck_total": Decimal("10000"),
        "description": "10,000 TCK — 100% bonus included",
    },
}

# ---------------------------------------------------------------------------
# Agent Evolution (levels)
# ---------------------------------------------------------------------------

ENFORCE_LEVEL_GATES = os.getenv("ENFORCE_LEVEL_GATES", "false").lower() == "true"
"""When False, level gates return warnings but don't block. Activate in production
when there's enough activity to make gates meaningful."""

LEVELS = (
    {"id": 0, "name": "Spawn",     "tck_spent": 0,     "cri_min": 0,  "emoji": "egg"},
    {"id": 1, "name": "Worker",    "tck_spent": 100,    "cri_min": 0,  "emoji": "gear"},
    {"id": 2, "name": "Artisan",   "tck_spent": 1000,   "cri_min": 50, "emoji": "hammer"},
    {"id": 3, "name": "Master",    "tck_spent": 10000,  "cri_min": 80, "emoji": "lightning"},
    {"id": 4, "name": "Architect", "tck_spent": 50000,  "cri_min": 95, "emoji": "temple"},
)
