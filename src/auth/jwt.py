"""
JWT verification utilities for Supabase tokens.

Supports ES256 (current Supabase signing) and HS256 (dev tokens).
"""
import logging
from typing import Any, Dict, Optional
from datetime import datetime, timezone

import jwt
import httpx
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError as JWTInvalidTokenError

from src.auth.config import SUPABASE_JWT_SECRET, SUPABASE_URL
from src.auth.exceptions import InvalidTokenError, TokenExpiredError

logger = logging.getLogger(__name__)

# Cached JWKS public keys (fetched once from Supabase)
_jwks_client: Optional[jwt.PyJWKClient] = None


def _get_jwks_client() -> jwt.PyJWKClient:
    """Get or create a PyJWKClient for Supabase JWKS."""
    global _jwks_client
    if _jwks_client is None:
        jwks_url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        _jwks_client = jwt.PyJWKClient(jwks_url)
    return _jwks_client


async def verify_supabase_token_async(token: str) -> Dict[str, Any]:
    """
    Verify a Supabase JWT token.

    Detects the algorithm from the token header:
    - ES256: Verifies using JWKS public key from Supabase (production tokens)
    - HS256: Verifies using SUPABASE_JWT_SECRET (dev tokens)
    """
    try:
        header = jwt.get_unverified_header(token)
    except Exception:
        raise InvalidTokenError("Malformed token")

    alg = header.get("alg", "HS256")

    try:
        if alg == "HS256":
            return _verify_hs256(token)
        else:
            return _verify_es256(token)
    except (InvalidTokenError, TokenExpiredError):
        raise
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise InvalidTokenError(f"Token verification failed")


def verify_supabase_token(token: str) -> Dict[str, Any]:
    """Sync version — only supports HS256 (dev tokens)."""
    return _verify_hs256(token)


def _verify_hs256(token: str) -> Dict[str, Any]:
    """Verify an HS256 token using the legacy JWT secret."""
    if not SUPABASE_JWT_SECRET:
        raise InvalidTokenError("SUPABASE_JWT_SECRET not configured")

    try:
        return jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except ExpiredSignatureError:
        raise TokenExpiredError()
    except JWTInvalidTokenError as e:
        logger.warning(f"Invalid HS256 token: {e}")
        raise InvalidTokenError()


def _verify_es256(token: str) -> Dict[str, Any]:
    """Verify an ES256 token using Supabase's JWKS public key."""
    try:
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)

        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
        )
    except ExpiredSignatureError:
        raise TokenExpiredError()
    except JWTInvalidTokenError as e:
        logger.warning(f"Invalid ES256 token: {e}")
        raise InvalidTokenError()


def extract_user_id(payload: Dict[str, Any]) -> str:
    """Extract the user ID (sub claim) from a decoded JWT payload."""
    user_id = payload.get("sub")
    if not user_id:
        raise InvalidTokenError("Token missing user ID (sub claim)")
    return user_id


def extract_email(payload: Dict[str, Any]) -> Optional[str]:
    """Extract the user's email from a decoded JWT payload."""
    return payload.get("email")


def extract_user_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract user metadata from a decoded JWT payload."""
    return payload.get("user_metadata", {})


def is_token_expired(payload: Dict[str, Any]) -> bool:
    """Check if the token has expired based on its exp claim."""
    exp = payload.get("exp")
    if not exp:
        return True
    return datetime.now(timezone.utc) > datetime.fromtimestamp(exp, tz=timezone.utc)


def create_dev_token(user_id: str, email: str, full_name: str, expires_in: int = 3600) -> str:
    """Create a development-only JWT token (HS256)."""
    if not SUPABASE_JWT_SECRET:
        raise InvalidTokenError("SUPABASE_JWT_SECRET not configured")

    now = datetime.now(timezone.utc)

    return jwt.encode(
        {
            "sub": user_id,
            "email": email,
            "aud": "authenticated",
            "role": "authenticated",
            "iat": int(now.timestamp()),
            "exp": int(now.timestamp() + expires_in),
            "user_metadata": {
                "full_name": full_name,
                "email": email,
            },
        },
        SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )
