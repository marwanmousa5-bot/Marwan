"""Maintenance, fuel, documents, costs, AI recommendations, audit."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Index, Integer,
                        JSON, String, Text)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (CostCategory, DocumentStatus, DocumentType,
                            MaintenanceCategory, MaintenanceStatus, Priority,
                            RecommendationStatus, WorkOrderStatus)
from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDMixin


class MaintenanceTemplate(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    """Reusable service definition applied to vehicle types (spec 7.6)."""
    __tablename__ = "maintenance_templates"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    vehicle_types: Mapped[list] = mapped_column(JSON, default=list)
    # [{category, label, estimated_cost, estimated_minutes}]
    items: Mapped[list] = mapped_column(JSON, default=list)
    interval_km: Mapped[float | None] = mapped_column(Float)
    interval_months: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class MaintenanceSchedule(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    """Preventive rule: every N km OR every N months, whichever comes first."""
    __tablename__ = "maintenance_schedules"

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("maintenance_templates.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(
        String(40), default=MaintenanceCategory.GENERAL_INSPECTION, nullable=False
    )
    interval_km: Mapped[float | None] = mapped_column(Float)
    interval_months: Mapped[int | None] = mapped_column(Integer)
    last_service_km: Mapped[float | None] = mapped_column(Float)
    last_service_date: Mapped[date | None] = mapped_column(Date)
    due_at_km: Mapped[float | None] = mapped_column(Float, index=True)
    due_at_date: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default=MaintenanceStatus.HEALTHY, nullable=False, index=True
    )
    priority: Mapped[str] = mapped_column(String(20), default=Priority.NORMAL, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_alerted_status: Mapped[str | None] = mapped_column(String(20))

    def km_remaining(self, odometer: float) -> float | None:
        return None if self.due_at_km is None else self.due_at_km - odometer

    def days_remaining(self, today: date) -> int | None:
        return None if self.due_at_date is None else (self.due_at_date - today).days


class WorkOrder(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "work_orders"

    reference: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("maintenance_schedules.id", ondelete="SET NULL")
    )
    workshop_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workshops.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), default=WorkOrderStatus.REQUESTED, nullable=False, index=True
    )
    priority: Mapped[str] = mapped_column(String(20), default=Priority.NORMAL, nullable=False)
    category: Mapped[str] = mapped_column(
        String(40), default=MaintenanceCategory.GENERAL_INSPECTION, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    problem: Mapped[str | None] = mapped_column(Text)
    diagnosis: Mapped[str | None] = mapped_column(Text)
    work_performed: Mapped[str | None] = mapped_column(Text)
    technician: Mapped[str | None] = mapped_column(String(120))

    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    expected_completion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_completion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    downtime_hours: Mapped[float | None] = mapped_column(Float)

    labor_hours: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    labor_rate: Mapped[float] = mapped_column(Float, default=75.0, nullable=False)
    labor_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    parts_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    odometer_km: Mapped[float | None] = mapped_column(Float)
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL", use_alter=True)
    )
    cancelled_reason: Mapped[str | None] = mapped_column(Text)

    parts: Mapped[list["WorkOrderPart"]] = relationship(
        back_populates="work_order", cascade="all, delete-orphan", lazy="selectin"
    )


class WorkOrderPart(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "work_order_parts"

    work_order_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(60))
    quantity: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    supplier: Mapped[str | None] = mapped_column(String(120))
    warranty_months: Mapped[int | None] = mapped_column(Integer)

    work_order: Mapped["WorkOrder"] = relationship(back_populates="parts")

    @property
    def total(self) -> float:
        return round(self.quantity * self.unit_cost, 2)


class MaintenanceRecord(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    """Completed service history used for cost/km, downtime and failure frequency."""
    __tablename__ = "maintenance_records"

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="SET NULL")
    )
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("maintenance_schedules.id", ondelete="SET NULL")
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    service_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    odometer_km: Mapped[float] = mapped_column(Float, nullable=False)
    work_performed: Mapped[str] = mapped_column(Text, nullable=False)
    parts_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    labor_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    downtime_hours: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    workshop_name: Mapped[str | None] = mapped_column(String(160))
    technician: Mapped[str | None] = mapped_column(String(120))


class FuelTransaction(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "fuel_transactions"

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="SET NULL"), index=True
    )
    place_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("places.id", ondelete="SET NULL")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    station_name: Mapped[str | None] = mapped_column(String(160))
    fuel_type: Mapped[str] = mapped_column(String(20), default="diesel", nullable=False)
    litres: Mapped[float] = mapped_column(Float, nullable=False)
    price_per_litre: Mapped[float] = mapped_column(Float, nullable=False)
    total_cost: Mapped[float] = mapped_column(Float, nullable=False)
    odometer_km: Mapped[float] = mapped_column(Float, nullable=False)
    # km covered since the previous fill, used for consumption maths
    distance_since_last_km: Mapped[float | None] = mapped_column(Float)
    is_full_tank: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(40))


class ChargingSession(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "charging_sessions"

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="SET NULL")
    )
    place_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("places.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location_name: Mapped[str | None] = mapped_column(String(160))
    energy_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    price_per_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    total_cost: Mapped[float] = mapped_column(Float, nullable=False)
    start_soc_pct: Mapped[float | None] = mapped_column(Float)
    end_soc_pct: Mapped[float | None] = mapped_column(Float)
    odometer_km: Mapped[float | None] = mapped_column(Float)


class Document(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "documents"

    type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)  # vehicle|driver|org
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), index=True
    )
    issuer: Mapped[str | None] = mapped_column(String(160))
    reference: Mapped[str | None] = mapped_column(String(80))
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default=DocumentStatus.VALID, nullable=False, index=True
    )
    attachment: Mapped[str | None] = mapped_column(Text)
    cost: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    last_alerted_days: Mapped[int | None] = mapped_column(Integer)


class CostRecord(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "cost_records"
    __table_args__ = (Index("ix_cost_org_date_cat", "organization_id", "incurred_on", "category"),)

    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    incurred_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[str | None] = mapped_column(String(30))
    source_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    odometer_km: Mapped[float | None] = mapped_column(Float)


class AIRecommendation(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    """Advisory until explicitly confirmed (spec 45)."""
    __tablename__ = "ai_recommendations"

    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(30), default="copilot", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    situation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    expected_impact: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=RecommendationStatus.PENDING, nullable=False, index=True
    )
    # Machine-readable plan the confirm endpoint executes.
    action: Mapped[dict | None] = mapped_column(JSON)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_note: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base, UUIDMixin):
    """Append-only. No update or delete path exists in the application."""
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_org_ts", "organization_id", "created_at"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    actor_email: Mapped[str | None] = mapped_column(String(160))
    actor_role: Mapped[str | None] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    entity_label: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))


class RoadDisruption(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    """Closures and weather cells that routing must react to (spec 25/26)."""
    __tablename__ = "road_disruptions"

    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # closure|weather|congestion
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    radius_m: Mapped[float] = mapped_column(Float, default=150.0, nullable=False)
    street: Mapped[str | None] = mapped_column(String(160))
    delay_minutes: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


class WeatherObservation(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "weather_observations"

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    condition: Mapped[str] = mapped_column(String(30), nullable=False)
    temperature_c: Mapped[float] = mapped_column(Float, nullable=False)
    wind_kph: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    precipitation_mm: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    visibility_m: Mapped[float] = mapped_column(Float, default=10000.0, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    radius_m: Mapped[float] = mapped_column(Float, default=600.0, nullable=False)
