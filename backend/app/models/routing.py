"""Planned routes and their stops (Section 4 item 8).

Geometry comes from a real routing engine (OSRM) - only the vehicle position
feed is simulated.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID, JSONB


class Route(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "routes"

    name: Mapped[str | None] = mapped_column(sa.String(200))
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="SET NULL"), index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("drivers.id", ondelete="SET NULL"), index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        sa.ForeignKey("tasks.id", ondelete="CASCADE", use_alter=True),
        index=True,
    )

    origin_latitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    origin_longitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    destination_latitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    destination_longitude: Mapped[float] = mapped_column(sa.Float, nullable=False)

    distance_km: Mapped[float | None] = mapped_column(sa.Float)
    duration_seconds: Mapped[int | None] = mapped_column(sa.Integer)
    #: OSRM-encoded polyline (precision 5) for the whole route.
    geometry_polyline: Mapped[str | None] = mapped_column(sa.Text)
    planned_departure_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )
    eta: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    #: Set when this route replaced another via Exception Auto-Rerouting.
    replaced_route_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("routes.id", ondelete="SET NULL")
    )
    reroute_reason: Mapped[str | None] = mapped_column(sa.String(300))


class RouteStop(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "route_stops"
    __table_args__ = (sa.Index("ix_route_stops_route_seq", "route_id", "sequence"),)

    route_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(sa.String(200))
    latitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    longitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    planned_arrival_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )
    actual_arrival_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    poi_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("points_of_interest.id", ondelete="SET NULL")
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)


class RoadClosure(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """A manually flagged disruption feeding Exception Auto-Rerouting."""

    __tablename__ = "road_closures"

    label: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    latitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    longitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    radius_m: Mapped[float] = mapped_column(sa.Float, default=500.0, nullable=False)
    active_from: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    active_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL")
    )
