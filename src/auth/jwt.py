"""
JWT verification utilities for Supabase tokens.
"""
import logging
from typing import Any, Dict, Optional
from datetime import datetime, timezone

import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError as JWTInvalidTokenError

from src.auth.config import SUPABASE_JWT_SECRET
from src.auth.exceptions import InvalidTokenError, TokenExpiredError

logger = logging.getLogger(__name__)


def verify_supabase_token(token: str) -> Dict[str, Any]:
    """
    Verify a Supabase JWT token and return the decoded payload.

    Args:
        token: The JWT token string (without "Bearer " prefix)

    Returns:
        Decoded JWT payload containing user claims

    Raises:
        InvalidTokenError: If the token is malformed or signature is invalid
        TokenExpiredError: If the token has expired
    """
    if not SUPABASE_JWT_SECRET:
        logger.error("SUPABASE_JWT_SECRET not configured")
        raise InvalidTokenError("Authentication not configured")

    try:
        # Supabase uses HS256 algorithm
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload

    except ExpiredSignatureError:
        raise TokenExpiredError()

    except JWTInvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        raise InvalidTokenError()


def extract_user_id(payload: Dict[str, Any]) -> str:
    """
    Extract the user ID from a decoded JWT payload.

    Args:
        payload: Decoded JWT payload

    Returns:
        The user's UUID (sub claim)

    Raises:
        InvalidTokenError: If the payload doesn't contain a valid user ID
    """
    user_id = payload.get("sub")
    if not user_id:
        raise InvalidTokenError("Token missing user ID (sub claim)")
    return user_id


def extract_email(payload: Dict[str, Any]) -> Optional[str]:
    """
    Extract the user's email from a decoded JWT payload.

    Args:
        payload: Decoded JWT payload

    Returns:
        The user's email or None if not present
    """
    return payload.get("email")


def extract_user_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract user metadata from a decoded JWT payload.

    This includes data from the OAuth provider (Google).

    Args:
        payload: Decoded JWT payload

    Returns:
        User metadata dict (may be empty)
    """
    return payload.get("user_metadata", {})


def is_token_expired(payload: Dict[str, Any]) -> bool:
    """
    Check if the token has expired based on its exp claim.

    Args:
        payload: Decoded JWT payload

    Returns:
        True if expired, False otherwise
    """
    exp = payload.get("exp")
    if not exp:
        return True

    exp_datetime = datetime.fromtimestamp(exp, tz=timezone.utc)
    return datetime.now(timezone.utc) > exp_datetime


def create_dev_token(user_id: str, email: str, full_name: str, expires_in: int = 3600) -> str:
    """
    Create a development-only JWT token.

    This should ONLY be used in local development mode.

    Args:
        user_id: The user's UUID
        email: User's email
        full_name: User's full name
        expires_in: Token expiry in seconds (default 1 hour)

    Returns:
        Signed JWT token string
    """
    if not SUPABASE_JWT_SECRET:
        raise InvalidTokenError("SUPABASE_JWT_SECRET not configured")

    now = datetime.now(timezone.utc)
    exp = now.timestamp() + expires_in

    payload = {
        "sub": user_id,
        "email": email,
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(now.timestamp()),
        "exp": int(exp),
        "user_metadata": {
            "full_name": full_name,
            "email": email,
        },
    }

    return jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")
