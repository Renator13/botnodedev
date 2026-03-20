"""JWT authentication flow tests."""
import secrets
from tests.conftest import register_and_verify


def test_jwt_authentication_flow(test_client):
    api_key, jwt_token, node_id = register_and_verify(test_client)

    # Access protected endpoint with Bearer token
    pub = test_client.post(
        "/v1/marketplace/publish",
        headers={"Authorization": f"Bearer {jwt_token}"},
        json={"type": "SKILL_OFFER", "label": "jwt-skill", "price_tck": 5.0, "metadata": {"auth": "jwt"}},
    )
    assert pub.status_code == 200
    assert pub.json()["status"] == "PUBLISHED"


def test_invalid_jwt_rejected(test_client):
    resp = test_client.post(
        "/v1/marketplace/publish",
        headers={"Authorization": "Bearer invalid.token.here"},
        json={"type": "SKILL_OFFER", "label": "fail", "price_tck": 1.0, "metadata": {}},
    )
    assert resp.status_code == 401
    assert "Invalid token" in resp.json()["detail"]


def test_missing_auth_rejected(test_client):
    resp = test_client.post(
        "/v1/marketplace/publish",
        json={"type": "SKILL_OFFER", "label": "fail", "price_tck": 1.0, "metadata": {}},
    )
    assert resp.status_code == 401
