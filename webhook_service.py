"""Webhook service — HMAC-SHA256 signing, dispatch, and delivery.

Events are dispatched synchronously during request handling (creating
delivery rows).  Actual HTTP delivery is handled by the webhook worker
(a background loop in main.py) that processes pending deliveries.

Signing follows the Stripe pattern:
    signature = HMAC-SHA256(secret, "{timestamp}.{payload}")
Headers sent:
    X-BotNode-Signature: <hex digest>
    X-BotNode-Timestamp: <unix timestamp>
    X-BotNode-Event: <event type>
"""

import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

import models
from dependencies import _utcnow

logger = logging.getLogger("botnode.webhooks")

WEBHOOK_EVENTS = [
    "task.created",
    "task.completed",
    "escrow.settled",
    "escrow.disputed",
    "escrow.refunded",
    "skill.purchased",
    "bounty.submission_won",
]

RETRY_INTERVALS = [60, 300, 1800]  # 1min, 5min, 30min
DELIVERY_TIMEOUT = 10  # seconds
MAX_WEBHOOKS_PER_NODE = 5


def generate_webhook_secret() -> str:
    """Generate a cryptographically random webhook secret (``whsec_`` prefix + 64 hex chars)."""
    return f"whsec_{secrets.token_hex(32)}"


def sign_payload(payload: str, secret: str, timestamp: int) -> str:
    """Compute HMAC-SHA256 signature over ``{timestamp}.{payload}``.

    The subscriber verifies by computing the same HMAC with their copy of
    the secret and comparing with ``X-BotNode-Signature``.
    """
    signed_content = f"{timestamp}.{payload}"
    return hmac.new(
        secret.encode("utf-8"),
        signed_content.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def dispatch_event(
    db: Session,
    event_type: str,
    data: dict,
    node_id: str,
) -> int:
    """Create delivery rows for all active subscriptions matching this event.

    Returns the number of deliveries created.
    """
    subs = (
        db.query(models.WebhookSubscription)
        .filter(
            models.WebhookSubscription.node_id == node_id,
            models.WebhookSubscription.active == True,
        )
        .all()
    )

    count = 0
    now = _utcnow()
    for sub in subs:
        events = sub.events if isinstance(sub.events, list) else json.loads(sub.events)
        if event_type not in events:
            continue

        payload = {
            "id": f"evt_{secrets.token_hex(12)}",
            "type": event_type,
            "created_at": now.isoformat() + "Z",
            "data": data,
        }

        delivery = models.WebhookDelivery(
            subscription_id=sub.id,
            event_type=event_type,
            payload=payload,
            status="pending",
            next_retry_at=now,
        )
        db.add(delivery)
        count += 1

    return count


def process_pending_deliveries(db: Session) -> dict:
    """Process pending webhook deliveries. Called by the webhook worker."""
    now = _utcnow()
    deliveries = (
        db.query(models.WebhookDelivery)
        .filter(
            models.WebhookDelivery.status == "pending",
            models.WebhookDelivery.next_retry_at <= now,
        )
        .limit(50)
        .all()
    )

    results = {"delivered": 0, "failed": 0, "exhausted": 0}

    for delivery in deliveries:
        sub = (
            db.query(models.WebhookSubscription)
            .filter(models.WebhookSubscription.id == delivery.subscription_id)
            .first()
        )
        if not sub or not sub.active:
            delivery.status = "failed"
            delivery.last_error = "subscription_inactive"
            db.commit()
            results["failed"] += 1
            continue

        payload_str = json.dumps(delivery.payload, ensure_ascii=False)
        timestamp = int(time.time())
        # Sign with the secret stored at creation time (subscriber has the same copy)
        signature = sign_payload(payload_str, sub.signing_secret, timestamp)

        headers = {
            "Content-Type": "application/json",
            "X-BotNode-Signature": signature,
            "X-BotNode-Timestamp": str(timestamp),
            "X-BotNode-Event": delivery.event_type,
            "User-Agent": "BotNode-Webhooks/1.0",
        }

        try:
            # Security: disable redirects (prevents SSRF via 301/302 to internal IPs)
            # and re-validate resolved IP at delivery time (prevents DNS rebinding)
            import socket, ipaddress as _ipa
            _hostname = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(sub.url).hostname or ""
            try:
                _resolved = socket.getaddrinfo(_hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
                for _, _, _, _, _addr in _resolved:
                    _ip = _ipa.ip_address(_addr[0])
                    if _ip.is_private or _ip.is_loopback or _ip.is_link_local or _ip.is_reserved:
                        raise ValueError(f"Webhook target resolves to blocked IP: {_addr[0]}")
            except (socket.gaierror, ValueError) as dns_err:
                raise Exception(f"DNS validation failed: {dns_err}")

            with httpx.Client(timeout=DELIVERY_TIMEOUT, follow_redirects=False) as client:
                response = client.post(sub.url, content=payload_str, headers=headers)

            delivery.last_attempt_at = now
            delivery.last_response_code = response.status_code
            delivery.attempts += 1

            if 200 <= response.status_code < 300:
                delivery.status = "delivered"
                db.commit()
                results["delivered"] += 1
            else:
                _handle_failure(delivery, f"HTTP {response.status_code}", now)
                db.commit()
                results["failed"] += 1
        except Exception as exc:
            delivery.last_attempt_at = now
            delivery.attempts += 1
            _handle_failure(delivery, str(exc)[:500], now)
            db.commit()
            results["failed"] += 1

    return results


def _handle_failure(delivery: models.WebhookDelivery, error: str, now: datetime) -> None:
    """Schedule a retry or mark delivery as exhausted after max attempts."""
    delivery.last_error = error
    if delivery.attempts >= len(RETRY_INTERVALS) + 1:
        delivery.status = "exhausted"
    else:
        retry_idx = min(delivery.attempts - 1, len(RETRY_INTERVALS) - 1)
        delivery.next_retry_at = now + timedelta(seconds=RETRY_INTERVALS[retry_idx])
        delivery.status = "pending"
