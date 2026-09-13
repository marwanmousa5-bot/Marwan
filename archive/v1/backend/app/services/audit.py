"""Append-only audit-log write path (Section 4 item 18).

Stood up in Phase 1 deliberately: every later phase logs its sensitive
actions through this one function as it is built, rather than having logging
bolted on retroactively. There is no update or delete counterpart here, and
none should ever be added.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal
from app.models.audit import AuditLog
from app.models.enums import AuditAction


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _user_agent(request: Request | None) -> str | None:
    if request is None:
        return None
    return (request.headers.get("user-agent") or "")[:500] or None


async def record(
    db: AsyncSession,
    *,
    action: AuditAction | str,
    principal: Principal | None = None,
    organization_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    summary: str | None = None,
    changes: dict[str, Any] | None = None,
    request: Request | None = None,
    actor_email: str | None = None,
    actor_role: str | None = None,
) -> AuditLog:
    """Insert one immutable audit row. Never raises on missing context."""
    entry = AuditLog(
        organization_id=(
            organization_id
            if organization_id is not None
            else (principal.organization_id if principal else None)
        ),
        actor_user_id=principal.user_id if principal else None,
        actor_email=actor_email or (principal.email if principal else None),
        actor_role=actor_role or (principal.role.value if principal else None),
        impersonator_user_id=principal.impersonator_id if principal else None,
        action=str(action),
        entity_type=entity_type,
        entity_id=entity_id,
        summary=(summary or "")[:400] or None,
        changes=changes,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
        request_id=getattr(getattr(request, "state", None), "request_id", None),
    )
    db.add(entry)
    await db.flush()
    return entry


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any] | None:
    """Build a compact {"before":…, "after":…} payload of changed fields only."""
    changed_before: dict[str, Any] = {}
    changed_after: dict[str, Any] = {}
    for key, new_value in after.items():
        old_value = before.get(key)
        if old_value != new_value:
            changed_before[key] = _jsonable(old_value)
            changed_after[key] = _jsonable(new_value)
    if not changed_after:
        return None
    return {"before": changed_before, "after": changed_after}


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def snapshot(obj: Any, fields: list[str]) -> dict[str, Any]:
    """Capture selected attributes of an ORM object for audit diffing."""
    return {field: _jsonable(getattr(obj, field, None)) for field in fields}
