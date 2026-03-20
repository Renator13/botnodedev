"""Per-node_id rate limiting using Redis.

Complements SlowAPI's per-IP rate limiting with identity-based limits.
An attacker rotating IPs cannot bypass per-node limits because the
node_id is extracted from the JWT/API key, not the network layer.

Uses Redis INCR + EXPIRE for O(1) checks with automatic key expiry.
Fails closed if Redis is unavailable — returns 429 with Retry-After
to prevent abuse during outages (Sybil registration, brute-force, etc.).
"""

import logging
import os
from typing import Optional

from fastapi import Request, HTTPException

logger = logging.getLogger("botnode.ratelimit")

# Limits: (max_requests, window_seconds)
NODE_RATE_LIMITS: dict[str, tuple[int, int]] = {
    "POST /v1/tasks/create":          (30, 60),   # 30 req/min
    "POST /v1/marketplace/publish":   (10, 60),   # 10 req/min
    "POST /v1/bounties":              (10, 60),   # 10 req/min
    "POST /v1/trade/escrow/init":     (20, 60),   # 20 req/min
    "POST /v1/trade/escrow/settle":   (20, 60),   # 20 req/min
    "POST /v1/webhooks":              (5,  60),   #  5 req/min
    "POST /v1/a2a/tasks/send":        (30, 60),   # 30 req/min
}
"""Per-endpoint (max_requests, window_seconds) limits keyed by ``METHOD /path``."""

# Redis connection (lazy init)
_redis_client: "redis.Redis | None" = None


def _get_redis() -> "redis.Redis | None":
    """Lazily initialize the Redis client.  Returns ``None`` if unavailable."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            url = os.getenv("REDIS_URL", "redis://redis:6379/0")
            _redis_client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1)
            _redis_client.ping()
        except Exception as exc:
            logger.warning("Redis unavailable for rate limiting: %s", exc)
            _redis_client = None
    return _redis_client


def check_node_rate_limit(node_id: str, method: str, path: str) -> Optional[int]:
    """Check if a node_id has exceeded its rate limit.

    Returns ``None`` if the request is allowed, or the number of seconds
    until the window resets (for the ``Retry-After`` header) if blocked.
    """
    key_lookup = f"{method} {path}"
    config = NODE_RATE_LIMITS.get(key_lookup)
    if not config:
        return None

    max_req, window = config
    r = _get_redis()
    if r is None:
        # fail-closed: if Redis is unavailable, block rate-limited endpoints
        # to prevent abuse during outages (Sybil registration, brute-force, etc.)
        logger.warning("Redis unavailable — fail-closed for %s", key_lookup)
        return 60  # block for 60 seconds, return Retry-After

    redis_key = f"rl:{node_id}:{key_lookup}"
    try:
        current = r.incr(redis_key)
        if current == 1:
            r.expire(redis_key, window)
        if current > max_req:
            ttl = r.ttl(redis_key)
            return max(ttl, 1)
    except Exception as exc:
        logger.warning("Rate limit check failed — fail-closed: %s", exc)
        return 60  # fail-closed on Redis errors too

    return None
