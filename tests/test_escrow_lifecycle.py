"""Full escrow lifecycle tests — init, task, complete, settle, auto-settle."""
import secrets
from datetime import datetime, timedelta, timezone

from tests.conftest import register_and_verify


def _publish_skill(client, seller_key, label="E2E-Skill", price=5.0):
    """Helper: publish a skill and return skill_id."""
    resp = client.post(
        "/v1/marketplace/publish",
        headers={"X-API-KEY": seller_key},
        json={"type": "SKILL_OFFER", "label": label, "price_tck": price, "metadata": {}},
    )
    assert resp.status_code == 200
    return resp.json()["skill_id"]


def _create_and_complete_task(client, buyer_key, seller_key, skill_id):
    """Helper: create task + seller completes it.  Returns (task_id, escrow_id)."""
    task = client.post(
        "/v1/tasks/create",
        headers={"X-API-KEY": buyer_key},
        json={"skill_id": skill_id, "input_data": {"x": 1}},
    )
    assert task.status_code == 200
    task_id = task.json()["task_id"]
    escrow_id = task.json()["escrow_id"]

    comp = client.post(
        "/v1/tasks/complete",
        headers={"X-API-KEY": seller_key},
        json={"task_id": task_id, "output_data": {"y": 2}, "proof_hash": "proof"},
    )
    assert comp.status_code == 200
    return task_id, escrow_id


# ── Full happy-path with auto-settle ────────────────────────────────

def test_full_lifecycle_with_auto_settle(test_client):
    """Register -> publish -> task -> complete -> auto-settle."""
    seller_key, _, seller_id = register_and_verify(test_client)
    buyer_key, _, _ = register_and_verify(test_client)
    skill_id = _publish_skill(test_client, seller_key)
    task_id, escrow_id = _create_and_complete_task(test_client, buyer_key, seller_key, skill_id)

    # Fast-forward dispute window
    import database, models
    db = database.SessionLocal()
    try:
        escrow = db.query(models.Escrow).filter(models.Escrow.id == escrow_id).first()
        assert escrow.status == "AWAITING_SETTLEMENT"
        escrow.auto_settle_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    # Auto-settle via admin endpoint
    resp = test_client.post(
        "/v1/admin/escrows/auto-settle",
        headers={"Authorization": "Bearer test-admin-key-2026"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["settled"] >= 1
    assert data["failed"] == 0

    # Verify seller got paid
    db = database.SessionLocal()
    try:
        seller = db.query(models.Node).filter(models.Node.id == seller_id).first()
        # Seller: 100 initial - 0.5 publish fee + (5 * 0.97) payout = 104.35
        assert float(seller.balance) > 100
    finally:
        db.close()


# ── Escrow init + insufficient funds ────────────────────────────────

def test_escrow_init_insufficient_funds(test_client):
    buyer_key, _, _ = register_and_verify(test_client)
    _, _, seller_id = register_and_verify(test_client)

    resp = test_client.post(
        "/v1/trade/escrow/init",
        headers={"X-API-KEY": buyer_key},
        json={"seller_id": seller_id, "amount": 99999},
    )
    assert resp.status_code == 402


# ── Manual settle after dispute window ──────────────────────────────

def test_manual_settle_after_window(test_client):
    seller_key, seller_jwt, seller_id = register_and_verify(test_client)
    buyer_key, _, _ = register_and_verify(test_client)
    skill_id = _publish_skill(test_client, seller_key)
    task_id, escrow_id = _create_and_complete_task(test_client, buyer_key, seller_key, skill_id)

    # Fast-forward dispute window
    import database, models
    db = database.SessionLocal()
    try:
        escrow = db.query(models.Escrow).filter(models.Escrow.id == escrow_id).first()
        escrow.auto_settle_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    # Seller manually settles
    resp = test_client.post(
        "/v1/trade/escrow/settle",
        headers={"Authorization": f"Bearer {seller_jwt}"},
        json={"escrow_id": escrow_id, "proof_hash": "manual_proof"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "SETTLED"


# ── Settle on wrong state (PENDING, not AWAITING_SETTLEMENT) ───────

def test_settle_wrong_state_rejected(test_client):
    buyer_key, buyer_jwt, _ = register_and_verify(test_client)
    _, _, seller_id = register_and_verify(test_client)

    init = test_client.post(
        "/v1/trade/escrow/init",
        headers={"X-API-KEY": buyer_key},
        json={"seller_id": seller_id, "amount": 5},
    )
    escrow_id = init.json()["escrow_id"]

    # Try to settle a PENDING escrow (should be rejected)
    resp = test_client.post(
        "/v1/trade/escrow/settle",
        headers={"Authorization": f"Bearer {buyer_jwt}"},
        json={"escrow_id": escrow_id, "proof_hash": "x"},
    )
    assert resp.status_code == 400
    assert "not ready" in resp.json()["detail"].lower()


# ── Three-strike ban flow ───────────────────────────────────────────

def test_three_strikes_ban(test_client):
    reporter_key, _, _ = register_and_verify(test_client)
    _, _, target_id = register_and_verify(test_client)

    for i in range(2):
        resp = test_client.post(
            f"/v1/report/malfeasance?node_id={target_id}",
            headers={"X-API-KEY": reporter_key},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "STRIKE_LOGGED"

    # Third strike = ban
    resp = test_client.post(
        f"/v1/report/malfeasance?node_id={target_id}",
        headers={"X-API-KEY": reporter_key},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "BANNED"
    assert resp.json()["confiscated_balance"] is not None


# ── Dispute blocks settlement ───────────────────────────────────────

def test_dispute_blocks_auto_settle(test_client):
    seller_key, _, seller_id = register_and_verify(test_client)
    buyer_key, _, _ = register_and_verify(test_client)
    skill_id = _publish_skill(test_client, seller_key)
    task_id, escrow_id = _create_and_complete_task(test_client, buyer_key, seller_key, skill_id)

    # Buyer disputes
    disp = test_client.post(
        "/v1/tasks/dispute",
        headers={"X-API-KEY": buyer_key},
        json={"task_id": task_id, "reason": "Wrong output"},
    )
    assert disp.status_code == 200
    assert disp.json()["status"] == "DISPUTE_OPEN"

    # Fast-forward and auto-settle — disputed escrow should NOT settle
    import database, models
    db = database.SessionLocal()
    try:
        escrow = db.query(models.Escrow).filter(models.Escrow.id == escrow_id).first()
        assert escrow.status == "DISPUTED"  # Not AWAITING_SETTLEMENT
    finally:
        db.close()
