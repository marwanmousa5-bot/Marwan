"""Alerts, alert rules, driver events, scoring, incidents."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Index, Integer,
                        JSON, String, Text)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import (AlertCategory, AlertStatus, IncidentStatus, IncidentType,
                            Severity)
from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDMixin


class AlertRule(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "alert_rules"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default=Severity.MEDIUM, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # WHEN <metric> <operator> <threshold> FOR <duration_s>
    metric: Mapped[str] = mapped_column(String(60), nullable=False)
    operator: Mapped[str] = mapped_column(String(10), default=">", nullable=False)
    threshold: Mapped[float | None] = mapped_column(Float)
    threshold_unit: Mapped[str | None] = mapped_column(String(20))
    duration_s: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    vehicle_ids: Mapped[list] = mapped_column(JSON, default=list)   # empty = all
    driver_ids: Mapped[list] = mapped_column(JSON, default=list)
    geofence_ids: Mapped[list] = mapped_column(JSON, default=list)

    notify_roles: Mapped[list] = mapped_column(JSON, default=list)
    notify_channels: Mapped[list] = mapped_column(JSON, default=lambda: ["in_app"])
    escalation_minutes: Mapped[list] = mapped_column(JSON, default=list)
    cooldown_s: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    dedupe_window_s: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    recommended_action: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def describe(self) -> str:
        parts = [f"WHEN {self.metric.replace('_', ' ')}"]
        if self.threshold is not None:
            parts.append(f"{self.operator} {self.threshold:g} {self.threshold_unit or ''}".strip())
        if self.duration_s:
            parts.append(f"FOR {self.duration_s}s")
        return " ".join(parts)


class Alert(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_org_status_sev", "organization_id", "status", "severity"),
    )

    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL"), index=True
    )
    code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default=AlertStatus.TRIGGERED, nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    recommended_action: Mapped[str | None] = mapped_column(Text)

    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="SET NULL"), index=True
    )
    trip_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trips.id", ondelete="SET NULL", use_alter=True)
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL", use_alter=True)
    )
    geofence_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("geofences.id", ondelete="SET NULL")
    )
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="SET NULL", use_alter=True)
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL", use_alter=True)
    )

    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    street: Mapped[str | None] = mapped_column(String(160))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)

    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalation_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Deduplication: repeated firings roll up into one alert (spec 6.8).
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_occurrence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_occurrence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str | None] = mapped_column(String(160), index=True)


class DriverEvent(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "driver_events"

    driver_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), index=True
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), index=True
    )
    trip_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE", use_alter=True), index=True
    )
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("alerts.id", ondelete="SET NULL", use_alter=True)
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), default=Severity.MEDIUM, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    street: Mapped[str | None] = mapped_column(String(160))
    value: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[str | None] = mapped_column(Text)


class DriverScoreSnapshot(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "driver_scores"
    __table_args__ = (Index("ix_driver_scores_driver_day", "driver_id", "day"),)

    driver_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    event_counts: Mapped[dict] = mapped_column(JSON, default=dict)


class DriverPointTransaction(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "driver_point_transactions"

    driver_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("driver_events.id", ondelete="SET NULL")
    )
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Badge(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "badges"

    driver_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str] = mapped_column(String(30), default="award")
    awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period: Mapped[str | None] = mapped_column(String(20))


class Incident(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "incidents"

    reference: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(30), default=IncidentType.OTHER, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default=Severity.MEDIUM, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=IncidentStatus.REPORTED, nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    address: Mapped[str | None] = mapped_column(String(255))

    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="SET NULL"), index=True
    )
    trip_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trips.id", ondelete="SET NULL", use_alter=True)
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL", use_alter=True)
    )
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="SET NULL", use_alter=True)
    )
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("alerts.id", ondelete="SET NULL", use_alter=True)
    )

    photos: Mapped[list] = mapped_column(JSON, default=list)
    documents: Mapped[list] = mapped_column(JSON, default=list)
    witnesses: Mapped[list] = mapped_column(JSON, default=list)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    reported_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)


class Inspection(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    """Driver pre-trip inspection (spec 28)."""
    __tablename__ = "inspections"

    driver_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), index=True
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)  # ready | issue_found
    items: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    photos: Mapped[list] = mapped_column(JSON, default=list)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL", use_alter=True)
    )
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="SET NULL", use_alter=True)
    )
