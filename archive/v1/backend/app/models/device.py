"""GPS device inventory - managed EXCLUSIVELY by platform staff (Section 4a)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID
from app.models.enums import DeviceStatus


class Device(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A physical GPS tracker owned by FleetBeat.

    A Device is *not* tenant-scoped in the usual sense: it lives in the
    platform inventory and is optionally assigned to an Organization +
    Vehicle. Customers get read-only visibility of the device linked to their
    own vehicles; they can never mutate this table (Section 9).
    """

    __tablename__ = "devices"

    serial_number: Mapped[str] = mapped_column(
        sa.String(64), nullable=False, unique=True, index=True
    )
    imei: Mapped[str | None] = mapped_column(sa.String(32), unique=True, index=True)
    model: Mapped[str | None] = mapped_column(sa.String(120))
    firmware_version: Mapped[str | None] = mapped_column(sa.String(64))
    notes: Mapped[str | None] = mapped_column(sa.Text)

    status: Mapped[str] = mapped_column(
        sa.String(32), default=DeviceStatus.IN_STOCK, nullable=False, index=True
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="SET NULL"), unique=True, index=True
    )

    assigned_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_signal_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    @property
    def is_live(self) -> bool:
        """Only an ACTIVE device attached to a vehicle produces position data."""
        return self.status == DeviceStatus.ACTIVE and self.vehicle_id is not None
