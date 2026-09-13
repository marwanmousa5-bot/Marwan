"""Driver profiles, the shared driver-event stream, points, and badges.

Section 4g is explicit that the safety score (Section 5 item 1) and the
points system read from ONE shared event stream - that is ``DriverEvent``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID, JSONB
from app.models.enums import EmploymentStatus

if TYPE_CHECKING:
    from app.models.user import User


class Driver(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "drivers"
    __table_args__ = (
        sa.Index("ix_drivers_org_status", "organization_id", "employment_status"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), unique=True, index=True
    )

    full_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    employee_number: Mapped[str | None] = mapped_column(sa.String(64))
    phone: Mapped[str | None] = mapped_column(sa.String(50))

    license_number: Mapped[str | None] = mapped_column(sa.String(64))
    license_class: Mapped[str | None] = mapped_column(sa.String(32))
    license_expiry: Mapped[date | None] = mapped_column(sa.Date, index=True)

    employment_status: Mapped[str] = mapped_column(
        sa.String(32), default=EmploymentStatus.ACTIVE, nullable=False
    )
    hired_on: Mapped[date | None] = mapped_column(sa.Date)

    assigned_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="SET NULL"), index=True
    )

    # --- Scores maintained by the AI layer (Section 5 item 1) ---
    safety_score: Mapped[float] = mapped_column(sa.Float, default=100.0, nullable=False)
    fatigue_risk_level: Mapped[str] = mapped_column(
        sa.String(16), default="low", nullable=False
    )
    fatigue_computed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )

    # --- Rewards & penalties (Section 4g) ---
    points_balance: Mapped[int] = mapped_column(sa.Integer, default=100, nullable=False)
    points_month: Mapped[str | None] = mapped_column(sa.String(7), index=True)

    user: Mapped[User | None] = relationship(
        back_populates="driver_profile", lazy="selectin"
    )


class DriverEvent(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """One shared behavioural-event stream (violations *and* rewards).

    Consumed by: safety scoring, fatigue indicator, points/leaderboard, and
    the Alerts Engine.
    """

    __tablename__ = "driver_events"
    __table_args__ = (
        sa.Index("ix_driver_events_driver_time", "driver_id", "occurred_at"),
        sa.Index("ix_driver_events_org_time", "organization_id", "occurred_at"),
    )

    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("drivers.id", ondelete="CASCADE"), index=True
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="SET NULL"), index=True
    )
    trip_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("trips.id", ondelete="SET NULL"), index=True
    )

    event_type: Mapped[str] = mapped_column(sa.String(40), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(sa.String(16), default="warning", nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, index=True
    )

    latitude: Mapped[float | None] = mapped_column(sa.Float)
    longitude: Mapped[float | None] = mapped_column(sa.Float)
    speed_kph: Mapped[float | None] = mapped_column(sa.Float)
    magnitude: Mapped[float | None] = mapped_column(sa.Float)
    details: Mapped[dict | None] = mapped_column(JSONB)

    # Set once the points engine has consumed this event (idempotency guard).
    points_applied: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, nullable=False, index=True
    )


class PointsLedgerEntry(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Append-only record of every points change, so a balance is explainable."""

    __tablename__ = "points_ledger_entries"
    __table_args__ = (
        sa.Index("ix_points_ledger_driver_time", "driver_id", "created_at"),
    )

    driver_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    driver_event_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("driver_events.id", ondelete="SET NULL")
    )
    delta: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    reason: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    period_month: Mapped[str] = mapped_column(sa.String(7), nullable=False, index=True)


class DriverBadge(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Awarded badge. The badge catalogue itself is backend-defined (Section 4g)."""

    __tablename__ = "driver_badges"
    __table_args__ = (
        sa.UniqueConstraint(
            "driver_id", "badge_code", "period_month", name="uq_driver_badge_period"
        ),
    )

    driver_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    badge_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    period_month: Mapped[str] = mapped_column(sa.String(7), nullable=False)
    awarded_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    context: Mapped[dict | None] = mapped_column(JSONB)
