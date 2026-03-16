import datetime as dt
from datetime import timezone
import jwt
from .jwt_keys import BOTNODE_JWT_PRIVATE_KEY, BOTNODE_JWT_PUBLIC_KEY

ISSUER = "botnode-orchestrator"
AUDIENCE = "botnode-grid"
ACCESS_TOKEN_EXPIRE_MINUTES = 15

def issue_access_token(node_id: str, role: str) -> str:
    """
    Issues an asymmetrically signed RS256 token.
    """
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
    """
    Verifies an RS256 token using the public key.
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
    except jwt.InvalidTokenError as e:
        return {"error": f"Invalid token: {str(e)}"}
