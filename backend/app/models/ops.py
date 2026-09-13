"""Operational core: routes, trips, positions, tasks, dispatch."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON,
                        String, Text)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import Priority, SlaState, TaskStatus, TaskType, TripStatus
from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDMixin


class Route(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "routes"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="SET NULL"), index=True
    )
    origin_lat: Mapped[float] = mapped_column(Float, nullable=False)
    origin_lon: Mapped[float] = mapped_column(Float, nullable=False)
    origin_name: Mapped[str | None] = mapped_column(String(160))
    dest_lat: Mapped[float] = mapped_column(Float, nullable=False)
    dest_lon: Mapped[float] = mapped_column(Float, nullable=False)
    dest_name: Mapped[str | None] = mapped_column(String(160))

    # Encoded planned geometry: [[lon,lat], ...] straight from the routing engine.
    geometry: Mapped[list] = mapped_column(JSON, default=list)
    distance_m: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # Per-leg breakdown so the UI can show progress between stops.
    legs: Mapped[list] = mapped_column(JSON, default=list)
    avoid_edges: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    optimized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    stops: Mapped[list["RouteStop"]] = relationship(
        back_populates="route", cascade="all, delete-orphan",
        order_by="RouteStop.sequence", lazy="selectin",
    )


class RouteStop(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "route_stops"

    route_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("routes.id", ondelete="CASCADE", use_alter=True), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    place_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("places.id", ondelete="SET NULL")
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL", use_alter=True)
    )
    stop_type: Mapped[str] = mapped_column(String(30), default="delivery")
    planned_arrival: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    service_minutes: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    departed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    route: Mapped["Route"] = relationship(back_populates="stops")


class Trip(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "trips"

    reference: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="SET NULL"), index=True
    )
    route_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("routes.id", ondelete="SET NULL", use_alter=True)
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL", use_alter=True), index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default=TripStatus.ACTIVE, nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    start_lat: Mapped[float | None] = mapped_column(Float)
    start_lon: Mapped[float | None] = mapped_column(Float)
    start_address: Mapped[str | None] = mapped_column(String(160))
    end_lat: Mapped[float | None] = mapped_column(Float)
    end_lon: Mapped[float | None] = mapped_column(Float)
    end_address: Mapped[str | None] = mapped_column(String(160))
    distance_km: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    idle_s: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_speed_kph: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_speed_kph: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    stop_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fuel_used_l: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    energy_used_kwh: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    co2_kg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    start_odometer_km: Mapped[float | None] = mapped_column(Float)
    end_odometer_km: Mapped[float | None] = mapped_column(Float)


class TripPosition(Base, UUIDMixin, OrgScopedMixin):
    """Every GPS sample required for playback is persisted here."""
    __tablename__ = "trip_positions"
    __table_args__ = (
        Index("ix_trip_positions_trip_ts", "trip_id", "recorded_at"),
    )

    trip_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), index=True
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    speed_kph: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    heading: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    odometer_km: Mapped[float | None] = mapped_column(Float)
    satellites: Mapped[int | None] = mapped_column(Integer)
    ignition: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    street: Mapped[str | None] = mapped_column(String(120))


class Customer(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    contact_name: Mapped[str | None] = mapped_column(String(120))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    contact_email: Mapped[str | None] = mapped_column(String(160))
    place_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("places.id", ondelete="SET NULL")
    )
    account_ref: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)


class Task(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "tasks"

    reference: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(30), default=TaskType.DELIVERY, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=TaskStatus.UNASSIGNED, nullable=False, index=True
    )
    priority: Mapped[str] = mapped_column(String(20), default=Priority.NORMAL, nullable=False)

    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), index=True
    )
    place_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("places.id", ondelete="SET NULL")
    )
    contact_name: Mapped[str | None] = mapped_column(String(120))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(String(255))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)

    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="SET NULL"), index=True
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), index=True
    )
    route_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("routes.id", ondelete="SET NULL", use_alter=True)
    )

    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    sla_minutes: Mapped[int | None] = mapped_column(Integer)
    sla_state: Mapped[str] = mapped_column(String(20), default=SlaState.NONE, nullable=False)
    eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    service_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    instructions: Mapped[str | None] = mapped_column(Text)
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    failure_reason: Mapped[str | None] = mapped_column(String(60))
    failure_note: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    # Proof of delivery
    pod_recipient: Mapped[str | None] = mapped_column(String(120))
    pod_signature: Mapped[str | None] = mapped_column(Text)
    pod_photo: Mapped[str | None] = mapped_column(Text)
    pod_notes: Mapped[str | None] = mapped_column(Text)
    pod_lat: Mapped[float | None] = mapped_column(Float)
    pod_lon: Mapped[float | None] = mapped_column(Float)
    pod_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class TimelineEvent(Base, UUIDMixin, OrgScopedMixin):
    """Immutable activity timeline shared by every important entity (spec 12)."""
    __tablename__ = "timeline_events"
    __table_args__ = (
        Index("ix_timeline_entity", "entity_type", "entity_id", "occurred_at"),
    )

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), default="system", nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    actor_name: Mapped[str] = mapped_column(String(160), default="System", nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    related_type: Mapped[str | None] = mapped_column(String(40))
    related_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
