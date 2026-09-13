"""Fuel and energy logging (manual entry for MVP, Section 4 item 7)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID
from app.models.enums import FuelType


class FuelLog(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "fuel_logs"
    __table_args__ = (
        sa.Index("ix_fuel_logs_vehicle_time", "vehicle_id", "filled_at"),
    )

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("drivers.id", ondelete="SET NULL"), index=True
    )

    fuel_type: Mapped[str] = mapped_column(
        sa.String(24), default=FuelType.PETROL, nullable=False
    )
    #: Litres for combustion vehicles, kWh for EV charging sessions.
    quantity: Mapped[float] = mapped_column(sa.Float, nullable=False)
    unit: Mapped[str] = mapped_column(sa.String(8), default="L", nullable=False)
    unit_price: Mapped[float | None] = mapped_column(sa.Numeric(12, 4))
    total_cost: Mapped[float] = mapped_column(sa.Numeric(12, 2), nullable=False)

    odometer_km: Mapped[float | None] = mapped_column(sa.Float)
    filled_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, index=True
    )
    location_name: Mapped[str | None] = mapped_column(sa.String(200))
    latitude: Mapped[float | None] = mapped_column(sa.Float)
    longitude: Mapped[float | None] = mapped_column(sa.Float)

    #: Battery percentage after an EV charging session.
    battery_level_after: Mapped[float | None] = mapped_column(sa.Float)
    #: Derived at write time so the carbon dashboard aggregates cheaply.
    co2_kg: Mapped[float | None] = mapped_column(sa.Float)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL")
    )
