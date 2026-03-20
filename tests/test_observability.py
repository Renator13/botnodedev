"""Tests for observability headers, public profile pages, and admin endpoint auth.

Covers VMP versioning headers, request-ID propagation, response timing,
the Genesis/node/skill HTML and JSON pages, and admin auth guards.
"""
import os

from rate_limit_node import NODE_RATE_LIMITS


# ---------------------------------------------------------------------------
# VMP-Version headers (T2.2)
# ---------------------------------------------------------------------------

def test_api_version_header_present(test_client):
    resp = test_client.get("/health")
    assert "VMP-Version" in resp.headers


def test_api_version_value(test_client):
    resp = test_client.get("/health")
    # The version is a date string in YYYY-MM-DD format
    version = resp.headers["VMP-Version"]
    parts = version.split("-")
    assert len(parts) == 3
    assert len(parts[0]) == 4  # year


def test_api_min_version_present(test_client):
    resp = test_client.get("/health")
    assert "VMP-Min-Version" in resp.headers


# ---------------------------------------------------------------------------
# Response timing header (T2.3)
# ---------------------------------------------------------------------------

def test_response_time_header_present(test_client):
    resp = test_client.get("/health")
    assert "X-Response-Time-Ms" in resp.headers
    # Should be a float-like string
    float(resp.headers["X-Response-Time-Ms"])


# ---------------------------------------------------------------------------
# Request-ID middleware
# ---------------------------------------------------------------------------

def test_request_id_header_present(test_client):
    resp = test_client.get("/health")
    assert "X-Request-ID" in resp.headers
    # Should be a UUID-like string
    rid = resp.headers["X-Request-ID"]
    assert len(rid) >= 32


def test_request_id_preserved_when_sent(test_client):
    custom_id = "my-custom-request-id-12345"
    resp = test_client.get("/health", headers={"X-Request-ID": custom_id})
    assert resp.headers["X-Request-ID"] == custom_id


def test_version_warning_on_mismatch(test_client):
    resp = test_client.get("/health", headers={"VMP-Version": "1999-01-01"})
    assert "VMP-Version-Warning" in resp.headers
    assert "1999-01-01" in resp.headers["VMP-Version-Warning"]


# ---------------------------------------------------------------------------
# Public profile pages — Genesis
# ---------------------------------------------------------------------------

def test_genesis_html_returns_200(test_client):
    resp = test_client.get("/genesis")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_genesis_html_has_og_tags(test_client):
    resp = test_client.get("/genesis")
    body = resp.text
    assert 'og:title' in body
    assert 'og:description' in body
    assert "Genesis" in body


def test_genesis_json_has_slots(test_client):
    resp = test_client.get("/v1/genesis/leaderboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "slots_total" in data
    assert data["slots_total"] == 200
    assert "slots_filled" in data
    assert "genesis_nodes" in data


# ---------------------------------------------------------------------------
# Public profile pages — 404 on non-existent
# ---------------------------------------------------------------------------

def test_node_404_on_nonexistent(test_client):
    resp = test_client.get("/v1/nodes/absolutely-does-not-exist-99999/profile")
    assert resp.status_code == 404


def test_skill_404_on_nonexistent(test_client):
    resp = test_client.get("/v1/skills/absolutely-does-not-exist-99999/page")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Admin endpoints — auth required
# ---------------------------------------------------------------------------

def test_metrics_requires_admin_auth(test_client):
    resp = test_client.get("/v1/admin/metrics")
    assert resp.status_code in (401, 403)


def test_reconcile_requires_admin_auth(test_client):
    resp = test_client.get("/v1/admin/ledger/reconcile")
    assert resp.status_code in (401, 403)


def test_dashboard_requires_admin_auth(test_client):
    resp = test_client.get("/v1/admin/dashboard")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Rate limit config
# ---------------------------------------------------------------------------

def test_rate_limit_config_exists():
    assert isinstance(NODE_RATE_LIMITS, dict)
    assert len(NODE_RATE_LIMITS) > 0
    # Each entry should be (max_requests, window_seconds)
    for key, value in NODE_RATE_LIMITS.items():
        assert isinstance(value, tuple)
        assert len(value) == 2
        max_req, window = value
        assert isinstance(max_req, int)
        assert isinstance(window, int)
        assert max_req > 0
        assert window > 0
