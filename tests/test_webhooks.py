"""Tests for the webhook system — secret generation, HMAC signing, and endpoints.

Covers both the low-level webhook_service functions and the HTTP endpoints
in routers/webhooks.py that require authentication.
"""
import hashlib
import hmac
from unittest.mock import MagicMock, patch

from webhook_service import (
    generate_webhook_secret,
    sign_payload,
    dispatch_event,
    WEBHOOK_EVENTS,
)


# ---------------------------------------------------------------------------
# generate_webhook_secret
# ---------------------------------------------------------------------------

def test_generate_webhook_secret_format():
    secret = generate_webhook_secret()
    assert secret.startswith("whsec_")
    # token_hex(32) produces 64 hex chars + "whsec_" prefix = 70 chars total
    assert len(secret) == 70


# ---------------------------------------------------------------------------
# sign_payload
# ---------------------------------------------------------------------------

def test_sign_payload_deterministic():
    sig1 = sign_payload("test-body", "whsec_abc123", 1700000000)
    sig2 = sign_payload("test-body", "whsec_abc123", 1700000000)
    assert sig1 == sig2


def test_sign_payload_matches_manual_hmac():
    payload = '{"event": "task.created"}'
    secret = "whsec_testsecret"
    timestamp = 1700000000

    expected = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{payload}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    actual = sign_payload(payload, secret, timestamp)
    assert actual == expected


# ---------------------------------------------------------------------------
# WEBHOOK_EVENTS constant
# ---------------------------------------------------------------------------

def test_webhook_events_list_has_7_items():
    assert len(WEBHOOK_EVENTS) == 7
    assert "task.created" in WEBHOOK_EVENTS
    assert "escrow.settled" in WEBHOOK_EVENTS
    assert "bounty.submission_won" in WEBHOOK_EVENTS


# ---------------------------------------------------------------------------
# HTTP endpoint tests (require test_client fixture from conftest)
# ---------------------------------------------------------------------------

def test_create_webhook_requires_auth(test_client):
    """POST /v1/webhooks without auth should return 401."""
    resp = test_client.post(
        "/v1/webhooks",
        json={"url": "https://example.com/hook", "events": ["task.created"]},
    )
    assert resp.status_code == 401


def test_list_webhooks_requires_auth(test_client):
    """GET /v1/webhooks without auth should return 401."""
    resp = test_client.get("/v1/webhooks")
    assert resp.status_code == 401


def test_webhook_url_must_be_https(test_client):
    """Webhook creation with http:// URL should be rejected (if auth passes).

    Since we cannot easily authenticate here, we verify the endpoint rejects
    unauthenticated requests first (auth check comes before URL validation).
    We test the URL validation logic indirectly via an authenticated request.
    """
    from tests.conftest import register_and_verify

    api_key, _, _ = register_and_verify(test_client)
    resp = test_client.post(
        "/v1/webhooks",
        headers={"X-API-KEY": api_key},
        json={"url": "http://example.com/hook", "events": ["task.created"]},
    )
    assert resp.status_code == 400
    assert "HTTPS" in resp.json()["detail"] or "https" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# dispatch_event
# ---------------------------------------------------------------------------

def test_dispatch_event_creates_delivery_rows():
    """dispatch_event should create a WebhookDelivery for each matching subscription."""
    db = MagicMock()

    # Simulate one active subscription that listens for task.created
    sub = MagicMock()
    sub.id = "sub-001"
    sub.events = ["task.created", "escrow.settled"]
    db.query.return_value.filter.return_value.all.return_value = [sub]

    count = dispatch_event(db, "task.created", {"task_id": "t-1"}, node_id="node-1")

    assert count == 1
    assert db.add.called
    delivery = db.add.call_args[0][0]
    assert delivery.subscription_id == "sub-001"
    assert delivery.event_type == "task.created"
    assert delivery.status == "pending"
