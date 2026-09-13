"""Password hashing and JWT issuing. Secrets come from settings only."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher(time_cost=2, memory_cost=32768, parallelism=2)


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, raw)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except Exception:
        return False


def validate_password_strength(raw: str) -> str | None:
    """Returns an error message, or None when acceptable."""
    if len(raw) < settings.password_min_length:
        return f"Password must be at least {settings.password_min_length} characters."
    if raw.lower() == raw or raw.upper() == raw:
        return "Password must mix upper and lower case letters."
    if not any(c.isdigit() for c in raw):
        return "Password must contain at least one digit."
    return None


def _encode(payload: dict, expires: timedelta, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    body = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + expires).timestamp()),
        "jti": uuid.uuid4().hex,
        "type": token_type,
    }
    return jwt.encode(body, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, role: str, org_id: uuid.UUID | None) -> str:
    return _encode(
        {"sub": str(user_id), "role": role, "org": str(org_id) if org_id else None},
        timedelta(minutes=settings.access_token_minutes),
        "access",
    )


def create_refresh_token(user_id: uuid.UUID) -> tuple[str, str, datetime]:
    """Returns (raw_token, sha256_hash, expiry). Only the hash is stored."""
    raw = _encode({"sub": str(user_id)}, timedelta(days=settings.refresh_token_days), "refresh")
    return raw, hash_token(raw), datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_days
    )


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def decode_token(token: str, expected_type: str = "access") -> dict | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != expected_type:
        return None
    return payload


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def device_fingerprint(user_agent: str | None, ip: str | None) -> str:
    return hashlib.sha256(f"{user_agent or ''}|{(ip or '').rsplit('.', 1)[0]}".encode()).hexdigest()[:32]
