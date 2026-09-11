"""Centralised alerts engine (Section 4 item 12)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID, JSONB
from app.models.enums import AlertSeverity, AlertStatus


class AlertRule(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Per-Organization configuration of one alert type."""

    __tablename__ = "alert_rules"
    __table_args__ = (
        sa.UniqueConstraint("organization_id", "rule_type", name="uq_alert_rule_per_org"),
    )

    rule_type: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    severity: Mapped[str] = mapped_column(
        sa.String(16), default=AlertSeverity.WARNING, nullable=False
    )
    #: Rule-specific parameters, e.g. {"speed_limit_kph": 110}
    parameters: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    notify_roles: Mapped[list | None] = mapped_column(
        JSONB, default=lambda: ["org_admin", "dispatcher"]
    )


class Alert(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        sa.Index("ix_alerts_org_status_time", "organization_id", "status", "created_at"),
        sa.Index("ix_alerts_dedupe", "organization_id", "dedupe_key"),
    )

    rule_type: Mapped[str] = mapped_column(sa.String(40), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(
        sa.String(16), default=AlertSeverity.WARNING, nullable=False
    )
    status: Mapped[str] = mapped_column(
        sa.String(24), default=AlertStatus.ACTIVE, nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)

    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("drivers.id", ondelete="CASCADE"), index=True
    )
    #: Free-form pointer to the originating record (work order, document, ...).
    subject_type: Mapped[str | None] = mapped_column(sa.String(40))
    subject_id: Mapped[uuid.UUID | None] = mapped_column(GUID)

    #: Stable key so a recurring condition does not spam duplicate alerts.
    dedupe_key: Mapped[str | None] = mapped_column(sa.String(200))
    context: Mapped[dict | None] = mapped_column(JSONB)

    acknowledged_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    acknowledged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
