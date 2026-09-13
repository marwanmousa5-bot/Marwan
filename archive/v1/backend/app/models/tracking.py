"""Trips, persisted position history, geofences and POIs.

Section 6 is explicit: EVERY position sample is persisted and linked to a
Trip so that Trip History Playback (Section 4c) can reconstruct a full route
after the fact. ``Vehicle.last_*`` is only a denormalised cache.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID, JSONB
from app.models.enums import GeofenceShape, GeofenceTrigger, PoiCategory, TripStatus


class Trip(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """A recorded execution: one continuous driving session for a vehicle."""

    __tablename__ = "trips"
    __table_args__ = (
        sa.Index("ix_trips_vehicle_start", "vehicle_id", "started_at"),
        sa.Index("ix_trips_org_start", "organization_id", "started_at"),
    )

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("drivers.id", ondelete="SET NULL"), index=True
    )
    # A Task is the assignment; the Trip is its recorded execution (Section 4f).
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        sa.ForeignKey("tasks.id", ondelete="SET NULL", use_alter=True),
        index=True,
    )

    status: Mapped[str] = mapped_column(
        sa.String(24), default=TripStatus.IN_PROGRESS, nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    start_latitude: Mapped[float | None] = mapped_column(sa.Float)
    start_longitude: Mapped[float | None] = mapped_column(sa.Float)
    end_latitude: Mapped[float | None] = mapped_column(sa.Float)
    end_longitude: Mapped[float | None] = mapped_column(sa.Float)

    distance_km: Mapped[float] = mapped_column(sa.Float, default=0.0, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    average_speed_kph: Mapped[float] = mapped_column(sa.Float, default=0.0, nullable=False)
    max_speed_kph: Mapped[float] = mapped_column(sa.Float, default=0.0, nullable=False)
    idle_seconds: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)

    start_odometer_km: Mapped[float | None] = mapped_column(sa.Float)
    end_odometer_km: Mapped[float | None] = mapped_column(sa.Float)
    estimated_fuel_litres: Mapped[float | None] = mapped_column(sa.Float)
    estimated_co2_kg: Mapped[float | None] = mapped_column(sa.Float)


class PositionSample(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    """A single GPS fix. High-volume table - kept deliberately narrow."""

    __tablename__ = "position_samples"
    __table_args__ = (
        sa.Index("ix_position_samples_trip_time", "trip_id", "recorded_at"),
        sa.Index("ix_position_samples_vehicle_time", "vehicle_id", "recorded_at"),
    )

    trip_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    latitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    longitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    speed_kph: Mapped[float] = mapped_column(sa.Float, default=0.0, nullable=False)
    heading: Mapped[float] = mapped_column(sa.Float, default=0.0, nullable=False)
    altitude_m: Mapped[float | None] = mapped_column(sa.Float)
    accuracy_m: Mapped[float | None] = mapped_column(sa.Float)
    ignition_on: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    #: "simulated" today; a real hardware provider later (Section 6).
    source: Mapped[str] = mapped_column(
        sa.String(32), default="simulated", nullable=False
    )


class Geofence(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """A polygon or circle drawn directly on the live map (Section 4d).

    Geometry is stored as plain JSON rather than PostGIS: MVP checks are done
    in Python with Shapely, which keeps the docker-compose stack to a stock
    ``postgres`` image. Swapping in PostGIS later only touches this column.
    """

    __tablename__ = "geofences"

    name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    shape: Mapped[str] = mapped_column(
        sa.String(16), default=GeofenceShape.POLYGON, nullable=False
    )
    #: polygon -> {"coordinates": [[lng, lat], ...]}
    #: circle  -> {"center": [lng, lat], "radius_m": 250}
    geometry: Mapped[dict] = mapped_column(JSONB, nullable=False)
    color: Mapped[str] = mapped_column(sa.String(9), default="#1E90FF", nullable=False)
    trigger: Mapped[str] = mapped_column(
        sa.String(16), default=GeofenceTrigger.BOTH, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    #: Empty list => applies to every vehicle in the Organization.
    vehicle_ids: Mapped[list | None] = mapped_column(JSONB, default=list)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL")
    )


class GeofenceEvent(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    __tablename__ = "geofence_events"
    __table_args__ = (
        sa.Index("ix_geofence_events_org_time", "organization_id", "occurred_at"),
    )

    geofence_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("geofences.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("drivers.id", ondelete="SET NULL")
    )
    direction: Mapped[str] = mapped_column(sa.String(8), nullable=False)  # enter | exit
    latitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    longitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )


class PointOfInterest(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "points_of_interest"

    name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    category: Mapped[str] = mapped_column(
        sa.String(32), default=PoiCategory.CUSTOM, nullable=False, index=True
    )
    latitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    longitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    address: Mapped[str | None] = mapped_column(sa.String(400))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL")
    )
