"""Append-only audit log (Section 4 item 18).

Stood up in Phase 1 so every later feature logs as it is built. Rows are
never updated or deleted through the application: the service layer only ever
INSERTs, and there is no update/delete endpoint anywhere in the API.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.types import GUID, JSONB


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        sa.Index("ix_audit_logs_org_time", "organization_id", "created_at"),
        sa.Index("ix_audit_logs_actor_time", "actor_user_id", "created_at"),
        sa.Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )

    #: NULL for platform-level actions with no tenant (e.g. super_admin login).
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor_email: Mapped[str | None] = mapped_column(sa.String(320))
    actor_role: Mapped[str | None] = mapped_column(sa.String(32))
    #: Set when a super_admin performed this while impersonating (Section 4a).
    impersonator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL")
    )

    action: Mapped[str] = mapped_column(sa.String(48), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(sa.String(64))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID)
    summary: Mapped[str | None] = mapped_column(sa.String(400))
    #: {"before": {...}, "after": {...}} for data changes.
    changes: Mapped[dict | None] = mapped_column(JSONB)

    ip_address: Mapped[str | None] = mapped_column(sa.String(64))
    user_agent: Mapped[str | None] = mapped_column(sa.String(500))
    request_id: Mapped[str | None] = mapped_column(sa.String(64))

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False,
        index=True,
    )
