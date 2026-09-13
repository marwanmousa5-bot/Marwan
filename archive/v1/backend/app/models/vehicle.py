"""Vehicle registry + asset-lifecycle fields (Section 4 items 3 and 15)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID
from app.models.enums import FuelType, VehicleOwnership, VehicleStatus, VehicleType

if TYPE_CHECKING:
    from app.models.device import Device


class Vehicle(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        sa.UniqueConstraint(
            "organization_id", "license_plate", name="uq_vehicle_plate_per_org"
        ),
        sa.Index("ix_vehicles_org_status", "organization_id", "status"),
    )

    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    make: Mapped[str | None] = mapped_column(sa.String(80))
    model: Mapped[str | None] = mapped_column(sa.String(80))
    year: Mapped[int | None] = mapped_column(sa.Integer)
    vin: Mapped[str | None] = mapped_column(sa.String(32), index=True)
    license_plate: Mapped[str] = mapped_column(sa.String(32), nullable=False)

    vehicle_type: Mapped[str] = mapped_column(
        sa.String(32), default=VehicleType.CAR, nullable=False
    )
    fuel_type: Mapped[str] = mapped_column(
        sa.String(32), default=FuelType.PETROL, nullable=False
    )
    ownership: Mapped[str] = mapped_column(
        sa.String(32), default=VehicleOwnership.OWNED, nullable=False
    )
    status: Mapped[str] = mapped_column(
        sa.String(32), default=VehicleStatus.ACTIVE, nullable=False
    )

    odometer_km: Mapped[float] = mapped_column(sa.Float, default=0.0, nullable=False)

    # --- EV fields (Section 4 item 7) ---
    battery_capacity_kwh: Mapped[float | None] = mapped_column(sa.Float)
    battery_level_percent: Mapped[float | None] = mapped_column(sa.Float)
    ev_range_km: Mapped[float | None] = mapped_column(sa.Float)

    # --- Asset lifecycle (Section 4 item 15) ---
    purchase_date: Mapped[date | None] = mapped_column(sa.Date)
    purchase_value: Mapped[float | None] = mapped_column(sa.Numeric(12, 2))
    residual_value: Mapped[float | None] = mapped_column(sa.Numeric(12, 2))
    useful_life_years: Mapped[int | None] = mapped_column(sa.Integer)
    replacement_recommended: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, nullable=False
    )
    ev_transition_candidate: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, nullable=False
    )

    # --- Denormalised "latest known position" for fast map bootstrapping.
    # The authoritative history lives in position_samples (Section 4c).
    last_latitude: Mapped[float | None] = mapped_column(sa.Float)
    last_longitude: Mapped[float | None] = mapped_column(sa.Float)
    last_heading: Mapped[float | None] = mapped_column(sa.Float)
    last_speed_kph: Mapped[float | None] = mapped_column(sa.Float)
    last_position_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    stopped_since: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    primary_driver_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        sa.ForeignKey("drivers.id", ondelete="SET NULL", use_alter=True),
        index=True,
    )

    device: Mapped[Device | None] = relationship(
        primaryjoin="Vehicle.id == foreign(Device.vehicle_id)",
        uselist=False,
        viewonly=True,
        lazy="selectin",
    )

    @property
    def is_tracked(self) -> bool:
        """A vehicle is live-tracked only when it has an active device."""
        return bool(self.device and self.device.is_live)
