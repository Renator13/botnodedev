"""Genesis badge lifecycle tests."""
import secrets
from tests.conftest import register_and_verify


def test_genesis_lifecycle(test_client):
    # 1. Early access signup
    email = f"genesis_{secrets.token_hex(4)}@test.com"
    ea = test_client.post("/v1/early-access", json={
        "email": email,
        "node_name": "GenesisPrime",
        "why_joining": "E2E test",
        "agent_type": "TEST_BOT",
    })
    assert ea.status_code == 200
    signup_token = ea.json()["signup_token"]
    assert signup_token.startswith("ea_")

    # 2. Register node with signup_token
    node_id = f"genesis-{secrets.token_hex(4)}"
    api_key, jwt_token, node_id = register_and_verify(
        test_client, node_id=node_id, signup_token=signup_token
    )

    # 3. Verify DB linking
    import database, models
    db = database.SessionLocal()
    try:
        signup = db.query(models.EarlyAccessSignup).filter(
            models.EarlyAccessSignup.signup_token == signup_token
        ).first()
        assert signup.linked_node_id == node_id

        node = db.query(models.Node).filter(models.Node.id == node_id).first()
        assert node.signup_token == signup_token
        assert node.first_settled_tx_at is None
        assert node.has_genesis_badge is False
    finally:
        db.close()

    # 4. Create a trade so seller gets first_settled_tx_at
    buyer_key, _, _ = register_and_verify(test_client)

    init = test_client.post(
        "/v1/trade/escrow/init",
        headers={"X-API-KEY": buyer_key},
        json={"seller_id": node_id, "amount": 10.0},
    )
    assert init.status_code == 200
    escrow_id = init.json()["escrow_id"]

    # 5. Complete task + settle via auto-settle (bypass dispute window for test)
    from datetime import datetime, timedelta, timezone
    db = database.SessionLocal()
    try:
        escrow = db.query(models.Escrow).filter(models.Escrow.id == escrow_id).first()
        escrow.status = "AWAITING_SETTLEMENT"
        escrow.auto_settle_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    auto = test_client.post(
        "/v1/admin/escrows/auto-settle",
        headers={"Authorization": "Bearer test-admin-key-2026"},
    )
    assert auto.status_code == 200
    assert auto.json()["settled"] >= 1

    # 6. Verify first_settled_tx_at was set, then manually trigger badge worker
    from worker import check_and_award_genesis_badges
    db = database.SessionLocal()
    try:
        node = db.query(models.Node).filter(models.Node.id == node_id).first()
        assert node.first_settled_tx_at is not None

        # Worker may not have been triggered yet if first_settled_tx_at was already set
        check_and_award_genesis_badges(db)
        db.commit()
        db.refresh(node)

        assert node.has_genesis_badge is True
        assert node.genesis_rank is not None
        assert node.balance > 400  # 100 initial + 300 bonus + trade payout
    finally:
        db.close()
