"""Organization, user, invitation, settings - the tenancy and identity core."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, JSON, String,
                        Text, UniqueConstraint)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import OrgStatus, Role
from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDMixin

# Defaults an organization can override. Nothing here is hardcoded in logic.
DEFAULT_ORG_SETTINGS: dict = {
    "currency": "EUR",
    "distance_unit": "km",
    "timezone": "Europe/Helsinki",
    "fuel_price_per_litre": 1.82,
    "energy_price_per_kwh": 0.17,
    "co2_kg_per_litre_diesel": 2.68,
    "co2_kg_per_litre_petrol": 2.31,
    "co2_kg_per_kwh": 0.061,
    "show_leaderboard_to_drivers": True,
    "driver_points_start": 100,
    "driver_points": {
        "overspeed": -5, "harsh_braking": -3, "harsh_acceleration": -3,
        "harsh_cornering": -2, "geofence_breach": -8, "route_deviation": -2,
        "idling": -1, "clean_streak": 10, "eco_driving": 5, "improvement": 8,
    },
    "safety_weights": {
        "overspeed": 6.0, "harsh_braking": 4.0, "harsh_acceleration": 3.5,
        "harsh_cornering": 3.0, "route_deviation": 2.0, "incident": 12.0,
    },
    "gps_live_threshold_s": 45,
    "gps_stale_threshold_s": 300,
    "document_alert_days": [30, 14, 7, 1],
    "maintenance_due_soon_km": 500,
    "maintenance_due_soon_days": 14,
    "alert_escalation_minutes": [5, 10],
    "sla_at_risk_minutes": 15,
    "maintenance_health_weights": {
        "overdue": 25, "critical": 30, "due": 10, "due_soon": 4,
        "open_work_order": 6, "repeat_failure": 15,
    },
    "ev_candidate_daily_km": 180,
}


class Organization(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default=OrgStatus.ACTIVE, nullable=False)
    country: Mapped[str] = mapped_column(String(80), default="Finland")
    city: Mapped[str] = mapped_column(String(80), default="Helsinki")
    contact_email: Mapped[str | None] = mapped_column(String(160))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    settings: Mapped[dict] = mapped_column(JSON, default=lambda: dict(DEFAULT_ORG_SETTINGS))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_reason: Mapped[str | None] = mapped_column(Text)

    users: Mapped[list["User"]] = relationship(back_populates="organization")

    def setting(self, key: str, default=None):
        merged = {**DEFAULT_ORG_SETTINGS, **(self.settings or {})}
        return merged.get(key, default)


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    # super_admin has no organization; everyone else must have one.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    avatar_color: Mapped[str] = mapped_column(String(16), default="#1E90FF")
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)

    organization: Mapped["Organization | None"] = relationship(back_populates="users")

    @property
    def is_super_admin(self) -> bool:
        return self.role == Role.SUPER_ADMIN


class Invitation(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "invitations"

    email: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(64))


class LoginAttempt(Base, UUIDMixin, TimestampMixin):
    """Feeds suspicious-login detection."""
    __tablename__ = "login_attempts"

    email: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    successful: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(80))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    device_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    is_new_device: Mapped[bool] = mapped_column(Boolean, default=False)
    is_new_location: Mapped[bool] = mapped_column(Boolean, default=False)


class SavedView(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    """Saved Live Tracking filter combinations (spec 2.5)."""
    __tablename__ = "saved_views"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    surface: Mapped[str] = mapped_column(String(40), default="live_tracking", nullable=False)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Notification(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    """Communication - deliberately separate from operational Alerts (spec 11)."""
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(255))
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
