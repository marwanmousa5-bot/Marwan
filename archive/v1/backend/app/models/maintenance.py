"""Preventive maintenance schedules, work orders and service history."""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID, JSONB
from app.models.enums import MaintenanceIntervalType, WorkOrderStatus


class MaintenanceSchedule(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """A recurring service rule, by mileage or by elapsed time."""

    __tablename__ = "maintenance_schedules"

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    component: Mapped[str | None] = mapped_column(sa.String(120))
    interval_type: Mapped[str] = mapped_column(
        sa.String(16), default=MaintenanceIntervalType.MILEAGE, nullable=False
    )
    interval_km: Mapped[float | None] = mapped_column(sa.Float)
    interval_days: Mapped[int | None] = mapped_column(sa.Integer)

    last_service_odometer_km: Mapped[float | None] = mapped_column(sa.Float)
    last_service_date: Mapped[date | None] = mapped_column(sa.Date)

    next_due_odometer_km: Mapped[float | None] = mapped_column(sa.Float)
    next_due_date: Mapped[date | None] = mapped_column(sa.Date, index=True)

    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)


class WorkOrder(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "work_orders"
    __table_args__ = (sa.Index("ix_work_orders_org_status", "organization_id", "status"),)

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("maintenance_schedules.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(
        sa.String(24), default=WorkOrderStatus.OPEN, nullable=False
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    odometer_km: Mapped[float | None] = mapped_column(sa.Float)
    labour_cost: Mapped[float | None] = mapped_column(sa.Numeric(12, 2))
    parts_cost: Mapped[float | None] = mapped_column(sa.Numeric(12, 2))
    total_cost: Mapped[float | None] = mapped_column(sa.Numeric(12, 2))
    vendor: Mapped[str | None] = mapped_column(sa.String(200))

    #: Set when the Maintenance Copilot proposed this window (Section 5 item 2).
    created_by_copilot: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, nullable=False
    )
    copilot_rationale: Mapped[str | None] = mapped_column(sa.Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL")
    )


class WorkOrderPart(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "work_order_parts"

    work_order_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    part_number: Mapped[str | None] = mapped_column(sa.String(80))
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    quantity: Mapped[float] = mapped_column(sa.Float, default=1.0, nullable=False)
    unit_cost: Mapped[float | None] = mapped_column(sa.Numeric(12, 2))


class ServiceRecord(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Immutable history entry written when a work order completes."""

    __tablename__ = "service_records"

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("work_orders.id", ondelete="SET NULL")
    )
    performed_on: Mapped[date] = mapped_column(sa.Date, nullable=False, index=True)
    odometer_km: Mapped[float | None] = mapped_column(sa.Float)
    summary: Mapped[str] = mapped_column(sa.String(400), nullable=False)
    total_cost: Mapped[float | None] = mapped_column(sa.Numeric(12, 2))
    details: Mapped[dict | None] = mapped_column(JSONB)
