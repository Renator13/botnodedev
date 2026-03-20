"""Webhook management endpoints.

Allows nodes to subscribe to events and receive HMAC-signed HTTP
notifications when those events occur.
"""

import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from dependencies import get_db, get_current_node
from webhook_service import (
    WEBHOOK_EVENTS,
    MAX_WEBHOOKS_PER_NODE,
    generate_webhook_secret,
)

router = APIRouter(tags=["webhooks"])


class WebhookCreateRequest(BaseModel):
    url: str = Field(..., max_length=500)
    events: List[str]


@router.post("/v1/webhooks")
def create_webhook(
    req: WebhookCreateRequest,
    node: models.Node = Depends(get_current_node),
    db: Session = Depends(get_db),
) -> dict:
    """Create a webhook subscription. The secret is returned ONCE."""
    if not req.url.startswith("https://"):
        raise HTTPException(400, "Webhook URL must use HTTPS")

    # SSRF protection: block internal/private network URLs
    from urllib.parse import urlparse
    import ipaddress
    hostname = urlparse(req.url).hostname or ""
    _blocked_prefixes = ("localhost", "127.", "0.0.0.0", "169.254.", "10.",
                         "192.168.", "[::1]", "fc00:", "fe80:", "fd")
    # Block entire 172.16.0.0/12 range (172.16.x - 172.31.x)
    _blocked_172 = tuple(f"172.{i}." for i in range(16, 32))
    _all_blocked = _blocked_prefixes + _blocked_172
    if any(hostname.startswith(b) or hostname == b.rstrip(".") for b in _all_blocked):
        raise HTTPException(400, "Webhook URL must not point to private/internal networks")
    # Also validate resolved IP is not private (catches DNS rebinding)
    try:
        import socket
        resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _, _, _, _, addr in resolved:
            ip = ipaddress.ip_address(addr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise HTTPException(400, "Webhook URL resolves to private/internal network")
    except (socket.gaierror, ValueError):
        raise HTTPException(400, "Webhook URL hostname could not be resolved")

    invalid = [e for e in req.events if e not in WEBHOOK_EVENTS]
    if invalid:
        raise HTTPException(400, f"Invalid events: {invalid}. Valid: {WEBHOOK_EVENTS}")

    existing = (
        db.query(models.WebhookSubscription)
        .filter(
            models.WebhookSubscription.node_id == node.id,
            models.WebhookSubscription.active == True,
        )
        .count()
    )
    if existing >= MAX_WEBHOOKS_PER_NODE:
        raise HTTPException(400, f"Maximum {MAX_WEBHOOKS_PER_NODE} webhooks per node")

    secret = generate_webhook_secret()

    sub = models.WebhookSubscription(
        node_id=node.id,
        url=req.url,
        signing_secret=secret,
        events=req.events,
        active=True,
    )
    db.add(sub)
    db.commit()

    return {
        "id": sub.id,
        "url": sub.url,
        "secret": secret,  # shown ONCE
        "events": req.events,
        "active": True,
        "verification_example": (
            "import hmac, hashlib\\n"
            "expected = hmac.new(secret.encode(), "
            "f'{timestamp}.{body}'.encode(), hashlib.sha256).hexdigest()\\n"
            "assert hmac.compare_digest(expected, signature)"
        ),
    }


@router.get("/v1/webhooks")
def list_webhooks(
    node: models.Node = Depends(get_current_node),
    db: Session = Depends(get_db),
) -> dict:
    """List webhooks for the authenticated node. Does NOT return secrets."""
    subs = (
        db.query(models.WebhookSubscription)
        .filter(
            models.WebhookSubscription.node_id == node.id,
            models.WebhookSubscription.active == True,
        )
        .all()
    )
    return {
        "webhooks": [
            {
                "id": s.id,
                "url": s.url,
                "events": s.events,
                "active": s.active,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in subs
        ]
    }


@router.delete("/v1/webhooks/{webhook_id}")
def delete_webhook(
    webhook_id: str,
    node: models.Node = Depends(get_current_node),
    db: Session = Depends(get_db),
) -> dict:
    """Deactivate a webhook subscription."""
    sub = (
        db.query(models.WebhookSubscription)
        .filter(models.WebhookSubscription.id == webhook_id)
        .first()
    )
    if not sub or sub.node_id != node.id:
        raise HTTPException(404, "Webhook not found")

    sub.active = False
    db.commit()
    return {"status": "deleted", "webhook_id": webhook_id}


@router.get("/v1/webhooks/{webhook_id}/deliveries")
def list_deliveries(
    webhook_id: str,
    status: Optional[str] = None,
    limit: int = 20,
    node: models.Node = Depends(get_current_node),
    db: Session = Depends(get_db),
) -> dict:
    """List delivery attempts for a webhook. For debugging."""
    sub = (
        db.query(models.WebhookSubscription)
        .filter(models.WebhookSubscription.id == webhook_id)
        .first()
    )
    if not sub or sub.node_id != node.id:
        raise HTTPException(404, "Webhook not found")

    query = (
        db.query(models.WebhookDelivery)
        .filter(models.WebhookDelivery.subscription_id == webhook_id)
        .order_by(models.WebhookDelivery.created_at.desc())
    )
    if status:
        query = query.filter(models.WebhookDelivery.status == status)

    deliveries = query.limit(limit).all()
    return {
        "deliveries": [
            {
                "id": d.id,
                "event_type": d.event_type,
                "status": d.status,
                "attempts": d.attempts,
                "last_response_code": d.last_response_code,
                "last_error": d.last_error,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in deliveries
        ]
    }
