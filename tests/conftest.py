import os
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Generate temporary RSA keys for testing immediately at import time
private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("utf-8")

public_key = private_key.public_key()
public_pem = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode("utf-8")

# Set all required env vars BEFORE any app import
os.environ["BOTNODE_JWT_PRIVATE_KEY"] = private_pem
os.environ["BOTNODE_JWT_PUBLIC_KEY"] = public_pem
os.environ["BOTNODE_ADMIN_TOKEN"] = "test-admin-token-2026"
os.environ["ADMIN_KEY"] = "test-admin-key-2026"
os.environ["INTERNAL_API_KEY"] = "test-internal-key-2026"
os.environ["DATABASE_URL"] = "sqlite:///./test_botnode.db"
os.environ["BASE_URL"] = "https://test.botnode.io"


def is_prime(n):
    if n < 2:
        return False
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0:
            return False
    return True


def register_and_verify(client, node_id=None, signup_token=None):
    """Helper: register + solve challenge + verify. Returns (api_key, jwt_token, node_id)."""
    import secrets as _secrets

    if not node_id:
        node_id = f"test-{_secrets.token_hex(4)}"

    reg_payload = {"node_id": node_id}
    if signup_token:
        reg_payload["signup_token"] = signup_token

    reg = client.post("/v1/node/register", json=reg_payload)
    assert reg.status_code == 200, f"Register failed: {reg.text}"

    payload = reg.json()["verification_challenge"]["payload"]
    solution = sum(n for n in payload if is_prime(n)) * 0.5

    verify_payload = {"node_id": node_id, "solution": solution}
    if signup_token:
        verify_payload["signup_token"] = signup_token

    verify = client.post("/v1/node/verify", json=verify_payload)
    assert verify.status_code == 200, f"Verify failed: {verify.text}"

    data = verify.json()
    return data["api_key"], data["session_token"], node_id


@pytest.fixture(scope="session")
def test_client():
    """Provide a TestClient with a clean SQLite DB and disabled rate limits."""
    from main import app, limiter
    from fastapi.testclient import TestClient

    # Disable rate limiting during tests
    limiter.enabled = False

    return TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """Ensure DB tables exist."""
    import models, database

    models.Base.metadata.create_all(bind=database.engine)
    yield
    # Cleanup
    os.remove("test_botnode.db") if os.path.exists("test_botnode.db") else None
