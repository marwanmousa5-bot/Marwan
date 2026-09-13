"""Password hashing, JWT issuance/verification and one-time link tokens."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

# Argon2id is used directly rather than through passlib: passlib is
# unmaintained and its bcrypt backend breaks against bcrypt>=4.
_hasher = PasswordHasher()

TokenType = Literal["access", "refresh"]


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True


def generate_password(length: int = 20) -> str:
    """Cryptographically random password used by the super-admin seeder."""
    alphabet = (
        "abcdefghijkmnopqrstuvwxyz"
        "ABCDEFGHJKLMNPQRSTUVWXYZ"
        "23456789"
        "!@#$%^&*-_=+"
    )
    return "".join(secrets.choice(alphabet) for _ in range(length))


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------

def _encode(
    payload: dict[str, Any], expires_delta: timedelta, token_type: TokenType
) -> str:
    now = datetime.now(UTC)
    to_encode = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": uuid.uuid4().hex,
        "type": token_type,
    }
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(
    *,
    user_id: uuid.UUID,
    role: str,
    organization_id: uuid.UUID | None,
    impersonator_id: uuid.UUID | None = None,
) -> str:
    """Mint an access token.

    ``organization_id`` is baked into the token and is the ONLY source of
    tenant scope for a request - a client-supplied organization_id is never
    trusted (Section 3).
    """
    return _encode(
        {
            "sub": str(user_id),
            "role": role,
            "org": str(organization_id) if organization_id else None,
            "imp": str(impersonator_id) if impersonator_id else None,
        },
        timedelta(minutes=settings.access_token_expire_minutes),
        "access",
    )


def create_refresh_token(*, user_id: uuid.UUID) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + timedelta(
        days=settings.refresh_token_expire_days
    )
    token = _encode(
        {"sub": str(user_id)},
        timedelta(days=settings.refresh_token_expire_days),
        "refresh",
    )
    return token, expires_at


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
    """Decode and validate a JWT. Raises ``jwt.PyJWTError`` on any problem."""
    payload = jwt.decode(
        token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
    )
    if expected_type and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected a {expected_type} token")
    return payload


# --------------------------------------------------------------------------
# One-time links (activation / password reset)
# --------------------------------------------------------------------------

def generate_link_token() -> tuple[str, str]:
    """Return ``(raw_token, token_hash)``.

    Only the hash is persisted, so database access alone cannot mint a
    working activation link.
    """
    raw = secrets.token_urlsafe(48)
    return raw, hash_link_token(raw)


def hash_link_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def device_fingerprint(user_agent: str | None, ip_address: str | None) -> str:
    """Coarse device identity for suspicious-login detection (Section 4 item 18)."""
    basis = f"{user_agent or 'unknown'}|{(ip_address or '').split('.')[0]}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:64]
