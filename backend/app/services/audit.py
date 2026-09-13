"""Append-only audit logging and entity timelines."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, TimelineEvent

# actions worth recording (spec 33)
LOGIN = "auth.login"
LOGIN_FAILED = "auth.login_failed"
LOGOUT = "auth.logout"
PASSWORD_CHANGED = "auth.password_changed"


def _jsonify(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    if isinstance(value, (uuid.UUID, datetime)):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def snapshot(obj, fields: list[str]) -> dict:
    """Small before/after snapshot of the fields an action actually touches."""
    return {f: _jsonify(getattr(obj, f, None)) for f in fields}


async def record(
    session: AsyncSession,
    *,
    action: str,
    organization_id: uuid.UUID | None = None,
    actor=None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    entity_label: str | None = None,
    summary: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        created_at=datetime.now(timezone.utc),
        organization_id=organization_id,
        actor_id=getattr(actor, "id", None),
        actor_email=getattr(actor, "email", None),
        actor_role=getattr(actor, "role", None),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        summary=summary,
        before=_jsonify(before) if before else None,
        after=_jsonify(after) if after else None,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:255] or None,
    )
    session.add(entry)
    return entry


async def timeline(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    description: str,
    actor=None,
    actor_type: str = "system",
    actor_name: str | None = None,
    related_type: str | None = None,
    related_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
    meta: dict | None = None,
) -> TimelineEvent:
    """Immutable activity entry shown on entity timelines (spec 12)."""
    if actor is not None:
        actor_type = "user"
        actor_name = actor_name or getattr(actor, "full_name", None) or getattr(actor, "email", "User")
    event = TimelineEvent(
        organization_id=organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        actor_type=actor_type,
        actor_id=getattr(actor, "id", None),
        actor_name=actor_name or "System",
        action=action,
        description=description,
        related_type=related_type,
        related_id=related_id,
        meta=_jsonify(meta or {}),
    )
    session.add(event)
    return event
