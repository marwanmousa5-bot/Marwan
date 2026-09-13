"""Incident / accident reporting (Section 4 item 11)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID
from app.models.enums import IncidentSeverity, IncidentStatus


class Incident(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "incidents"
    __table_args__ = (
        sa.Index("ix_incidents_org_time", "organization_id", "occurred_at"),
    )

    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text)
    severity: Mapped[str] = mapped_column(
        sa.String(16), default=IncidentSeverity.MINOR, nullable=False
    )
    status: Mapped[str] = mapped_column(
        sa.String(24), default=IncidentStatus.REPORTED, nullable=False
    )

    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="SET NULL"), index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("drivers.id", ondelete="SET NULL"), index=True
    )
    trip_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("trips.id", ondelete="SET NULL")
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("tasks.id", ondelete="SET NULL")
    )
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("work_orders.id", ondelete="SET NULL")
    )

    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    latitude: Mapped[float | None] = mapped_column(sa.Float)
    longitude: Mapped[float | None] = mapped_column(sa.Float)
    location_label: Mapped[str | None] = mapped_column(sa.String(300))
    estimated_cost: Mapped[float | None] = mapped_column(sa.Numeric(12, 2))

    reported_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL")
    )


class IncidentPhoto(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "incident_photos"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    file_url: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    file_name: Mapped[str | None] = mapped_column(sa.String(255))
    caption: Mapped[str | None] = mapped_column(sa.String(300))
