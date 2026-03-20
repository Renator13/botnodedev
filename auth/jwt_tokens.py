"""RS256 JWT issuance and verification for node session tokens.

Tokens are short-lived (15 min), audience/issuer-scoped, and signed
with an asymmetric key-pair so that downstream services can validate
tokens using the public key alone.
"""

import datetime as dt
from datetime import timezone

import jwt

from .jwt_keys import BOTNODE_JWT_PRIVATE_KEY, BOTNODE_JWT_PUBLIC_KEY

ISSUER = "botnode-orchestrator"
AUDIENCE = "botnode-grid"
ACCESS_TOKEN_EXPIRE_MINUTES = 15


def issue_access_token(node_id: str, role: str) -> str:
    """Create and return a signed RS256 JWT for *node_id*."""
    now = dt.datetime.now(timezone.utc)
    payload = {
        "sub": node_id,
        "role": role,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + dt.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    if not BOTNODE_JWT_PRIVATE_KEY:
        raise ValueError("Private key missing in environment")
    return jwt.encode(payload, BOTNODE_JWT_PRIVATE_KEY, algorithm="RS256")


def verify_access_token(token: str) -> dict:
    """Decode and verify an RS256 JWT.

    Returns the decoded claims on success, or a dict with an ``"error"``
    key on failure (expired, invalid signature, etc.).
    """
    if not BOTNODE_JWT_PUBLIC_KEY:
        raise ValueError("Public key missing in environment")
    try:
        return jwt.decode(
            token,
            BOTNODE_JWT_PUBLIC_KEY,
            algorithms=["RS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
        )
    except jwt.ExpiredSignatureError:
        return {"error": "Token expired"}
    except jwt.InvalidTokenError as exc:
        return {"error": f"Invalid token: {exc}"}
