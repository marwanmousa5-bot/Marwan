"""Dispatch tasks (Section 4f).

A Task is the *assignment*; the Trip it generates on acceptance is the
*recorded execution*.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID, JSONB
from app.models.enums import TaskPriority, TaskStatus, TaskType


class Task(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        sa.Index("ix_tasks_org_status", "organization_id", "status"),
        sa.Index("ix_tasks_driver_status", "driver_id", "status"),
    )

    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text)
    task_type: Mapped[str] = mapped_column(
        sa.String(24), default=TaskType.DELIVERY, nullable=False
    )
    priority: Mapped[str] = mapped_column(
        sa.String(16), default=TaskPriority.NORMAL, nullable=False
    )
    status: Mapped[str] = mapped_column(
        sa.String(24), default=TaskStatus.ASSIGNED, nullable=False, index=True
    )

    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("drivers.id", ondelete="SET NULL"), index=True
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="SET NULL"), index=True
    )

    destination_label: Mapped[str | None] = mapped_column(sa.String(300))
    destination_latitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    destination_longitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    #: [{"lat":.., "lng":.., "label":".."}, ...]
    waypoints: Mapped[list | None] = mapped_column(JSONB, default=list)

    due_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    eta: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    accepted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(sa.String(300))

    completion_note: Mapped[str | None] = mapped_column(sa.Text)
    completion_photo_url: Mapped[str | None] = mapped_column(sa.String(500))

    route_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("routes.id", ondelete="SET NULL")
    )
    trip_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("trips.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL")
    )


class PreTripInspection(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Driver pre-trip checklist submitted from the mobile app (Phase 3)."""

    __tablename__ = "pre_trip_inspections"

    driver_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("tasks.id", ondelete="SET NULL")
    )
    submitted_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    #: [{"code":"tyres","label":"Tyres","ok":true,"note":null}, ...]
    items: Mapped[list] = mapped_column(JSONB, nullable=False)
    passed: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    odometer_km: Mapped[float | None] = mapped_column(sa.Float)
    notes: Mapped[str | None] = mapped_column(sa.Text)
