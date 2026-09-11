"""Audit log and login-activity read schemas (Section 4 item 18, Section 7)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class AuditLogOut(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    actor_user_id: uuid.UUID | None = None
    actor_email: str | None = None
    actor_role: str | None = None
    impersonator_user_id: uuid.UUID | None = None
    action: str
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    summary: str | None = None
    changes: dict | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime
    #: Filled in for the platform-wide view so rows are readable without a
    #: second lookup per organization.
    organization_name: str | None = None


class LoginAttemptOut(ORMModel):
    id: uuid.UUID
    email: str
    user_id: uuid.UUID | None = None
    successful: bool
    ip_address: str | None = None
    user_agent: str | None = None
    suspicious: bool
    suspicion_reason: str | None = None
    attempted_at: datetime


class KnownDeviceOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    label: str | None = None
    last_ip: str | None = None
    last_seen_at: datetime | None = None
    created_at: datetime


class SecurityOverview(BaseModel):
    """What an admin needs to see at a glance on the security screen."""

    suspicious_logins_7d: int
    failed_logins_7d: int
    locked_accounts: int
    users_without_a_known_device: int
