"""MCP bridge, admin endpoints, wallet, branding headers, and static routes."""
import secrets
from datetime import datetime, timedelta, timezone

from tests.conftest import register_and_verify


# ── MCP Wallet ──────────────────────────────────────────────────────

def test_mcp_wallet(test_client):
    _, jwt, _ = register_and_verify(test_client)
    resp = test_client.get(
        "/v1/mcp/wallet",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "balance_tck" in data
    assert data["pending_escrows"] == 0
    assert data["open_tasks"] == 0


def test_mcp_wallet_no_auth(test_client):
    resp = test_client.get("/v1/mcp/wallet")
    assert resp.status_code == 401


# ── MCP Hire (invalid capability) ──────────────────────────────────

def test_mcp_hire_invalid_capability(test_client):
    _, jwt, _ = register_and_verify(test_client)
    resp = test_client.post(
        "/v1/mcp/hire",
        headers={"Authorization": f"Bearer {jwt}"},
        json={
            "integration": "claude",
            "capability": "does-not-exist",
            "payload": {},
            "max_price": 5.0,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error_type"] == "INVALID_CAPABILITY"


def test_mcp_hire_low_price(test_client):
    _, jwt, _ = register_and_verify(test_client)
    resp = test_client.post(
        "/v1/mcp/hire",
        headers={"Authorization": f"Bearer {jwt}"},
        json={
            "integration": "claude",
            "capability": "web-research",
            "payload": {},
            "max_price": 0.01,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error_type"] == "BAD_PAYLOAD"


# ── Admin sync node ────────────────────────────────────────────────

def test_admin_sync_node_create(test_client):
    node_id = f"synced-{secrets.token_hex(4)}"
    resp = test_client.post(
        "/api/v1/admin/sync/node",
        headers={"Authorization": "Bearer test-admin-token-2026"},
        json={
            "id": node_id,
            "api_key_hash": "synced_hash",
            "balance": 500.0,
            "reputation_score": 1.0,
            "active": True,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["node_id"] == node_id


def test_admin_sync_node_update(test_client):
    node_id = f"sync-upd-{secrets.token_hex(4)}"
    # Create
    test_client.post(
        "/api/v1/admin/sync/node",
        headers={"Authorization": "Bearer test-admin-token-2026"},
        json={"id": node_id, "api_key_hash": "h", "balance": 100, "active": True},
    )
    # Update balance
    resp = test_client.post(
        "/api/v1/admin/sync/node",
        headers={"Authorization": "Bearer test-admin-token-2026"},
        json={"id": node_id, "balance": 999},
    )
    assert resp.status_code == 200


def test_admin_sync_node_no_auth(test_client):
    resp = test_client.post(
        "/api/v1/admin/sync/node",
        headers={"Authorization": "Bearer wrong"},
        json={"id": "x", "api_key_hash": "x"},
    )
    assert resp.status_code == 401


# ── Admin stats periods ────────────────────────────────────────────

def test_admin_stats_periods(test_client):
    for period in ["24h", "7d", "30d", "all"]:
        resp = test_client.get(
            f"/v1/admin/stats?period={period}",
            headers={"Authorization": "Bearer test-admin-key-2026"},
        )
        assert resp.status_code == 200
        assert resp.json()["period"] == period


# ── Branding headers ───────────────────────────────────────────────

def test_branding_headers_on_api(test_client):
    """API responses carry the marketing headers."""
    resp = test_client.get("/v1/marketplace")
    assert "X-Accepts-Payment" in resp.headers
    assert "Ticks" in resp.headers["X-Accepts-Payment"]
    assert "Link" in resp.headers
    assert "mission.json" in resp.headers["Link"]


# ── Early access signup ────────────────────────────────────────────

def test_early_access_signup(test_client):
    email = f"ea-{secrets.token_hex(4)}@test.io"
    resp = test_client.post("/v1/early-access", json={
        "email": email,
        "node_name": "TestBot",
        "agent_type": "research",
        "primary_capability": "web-search",
        "why_joining": "Testing",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["signup_token"].startswith("ea_")
    assert data["status"] == "pre_eligible"


def test_early_access_invalid_email(test_client):
    resp = test_client.post("/v1/early-access", json={
        "email": "not-an-email",
    })
    assert resp.status_code == 422


# ── Static routes ──────────────────────────────────────────────────

def test_health_endpoint(test_client):
    resp = test_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert "timestamp" in data


def test_mission_json(test_client):
    resp = test_client.get("/mission.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["protocol"] == "VMP-1.0"
    assert "discovery_endpoint" in data


# ── Genesis hall of fame (empty is OK) ─────────────────────────────

def test_genesis_hall_of_fame(test_client):
    resp = test_client.get("/v1/genesis")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Marketplace search/filter ──────────────────────────────────────

def test_marketplace_search(test_client):
    seller_key, _, _ = register_and_verify(test_client)
    test_client.post(
        "/v1/marketplace/publish",
        headers={"X-API-KEY": seller_key},
        json={"type": "SKILL_OFFER", "label": "UniqueSearchTest", "price_tck": 3.0, "metadata": {}},
    )
    resp = test_client.get("/v1/marketplace?q=UniqueSearch")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


def test_marketplace_price_filter(test_client):
    resp = test_client.get("/v1/marketplace?min_price=0.1&max_price=100")
    assert resp.status_code == 200
    assert "listings" in resp.json()


# ── Node badge CRI recalculation ───────────────────────────────────

def test_badge_triggers_cri_recalculation(test_client):
    """Badge endpoint should recalculate CRI if stale."""
    _, _, node_id = register_and_verify(test_client)

    # Force cri_updated_at to be old
    import database, models
    db = database.SessionLocal()
    try:
        node = db.query(models.Node).filter(models.Node.id == node_id).first()
        node.cri_updated_at = None  # Force recalc
        db.commit()
    finally:
        db.close()

    resp = test_client.get(f"/v1/node/{node_id}/badge.svg")
    assert resp.status_code == 200
    assert "CRI:" in resp.text

    # CRI should now be updated
    db = database.SessionLocal()
    try:
        node = db.query(models.Node).filter(models.Node.id == node_id).first()
        assert node.cri_updated_at is not None
        assert node.cri_score is not None
    finally:
        db.close()
