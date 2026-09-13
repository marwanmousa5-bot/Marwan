"""Organization (tenant) and its per-Organization settings."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID, JSONB
from app.models.enums import OrganizationStatus, SubscriptionStatus

if TYPE_CHECKING:
    from app.models.user import User


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A customer tenant. Created ONLY by a super_admin (Section 4a)."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(sa.String(200), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(sa.String(200), nullable=False, unique=True)
    industry: Mapped[str | None] = mapped_column(sa.String(120))
    timezone: Mapped[str] = mapped_column(sa.String(64), default="UTC", nullable=False)

    contact_name: Mapped[str | None] = mapped_column(sa.String(200))
    contact_email: Mapped[str | None] = mapped_column(sa.String(320))
    contact_phone: Mapped[str | None] = mapped_column(sa.String(50))

    logo_url: Mapped[str | None] = mapped_column(sa.String(500))
    primary_color: Mapped[str | None] = mapped_column(sa.String(9))

    status: Mapped[str] = mapped_column(
        sa.String(32), default=OrganizationStatus.ACTIVE, nullable=False, index=True
    )

    # Reserved for a future billing phase - never enforced (Section 2).
    plan: Mapped[str] = mapped_column(sa.String(50), default="standard", nullable=False)
    subscription_status: Mapped[str] = mapped_column(
        sa.String(32), default=SubscriptionStatus.TRIAL, nullable=False
    )

    settings: Mapped[OrganizationSettings] = relationship(
        back_populates="organization",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    users: Mapped[list[User]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )

    @property
    def is_active(self) -> bool:
        return self.status == OrganizationStatus.ACTIVE


#: Default point weights for the Rewards & Penalty system (Section 4g).
#: Org-Admin configurable - these are defaults only, never hardcoded logic.
DEFAULT_POINT_WEIGHTS: dict[str, int] = {
    "harsh_braking": -3,
    "harsh_acceleration": -3,
    "speeding": -5,
    "geofence_breach": -5,
    "clean_streak": 10,
    "fuel_efficient": 5,
}

#: Default alert thresholds, per Organization.
DEFAULT_ALERT_THRESHOLDS: dict[str, float] = {
    "speeding_kph": 110.0,
    "harsh_braking_ms2": -3.5,
    "harsh_acceleration_ms2": 3.0,
    "idle_minutes": 15.0,
    "document_expiry_warning_days": 30.0,
    "maintenance_due_km": 500.0,
    "maintenance_due_days": 14.0,
    "fatigue_continuous_driving_hours": 4.5,
    "fatigue_min_rest_hours": 8.0,
}


class OrganizationSettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tunable per-Organization behaviour.

    Anything an Org Admin can tune lives here rather than in code, per the
    Section 9 constraint against hardcoded point weights.
    """

    __tablename__ = "organization_settings"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    distance_unit: Mapped[str] = mapped_column(sa.String(8), default="km", nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(8), default="USD", nullable=False)

    # Section 4g
    show_leaderboard_to_drivers: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, nullable=False
    )
    driver_points_baseline: Mapped[int] = mapped_column(
        sa.Integer, default=100, nullable=False
    )
    point_weights: Mapped[dict] = mapped_column(
        JSONB, default=lambda: dict(DEFAULT_POINT_WEIGHTS), nullable=False
    )

    # Section 5 item 2 - default OFF because auto-created work orders cost money.
    maintenance_auto_book_enabled: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, nullable=False
    )

    alert_thresholds: Mapped[dict] = mapped_column(
        JSONB, default=lambda: dict(DEFAULT_ALERT_THRESHOLDS), nullable=False
    )

    # Section 4 item 17 - kg CO2 per litre of fuel burned, by fuel type.
    co2_emission_factors: Mapped[dict] = mapped_column(
        JSONB,
        default=lambda: {"petrol": 2.31, "diesel": 2.68, "lpg": 1.51, "electric": 0.0},
        nullable=False,
    )

    organization: Mapped[Organization] = relationship(back_populates="settings")

    def point_weight(self, event_type: str) -> int:
        """Resolve a configured weight, falling back to the shipped default."""
        weights = self.point_weights or {}
        if event_type in weights:
            return int(weights[event_type])
        return int(DEFAULT_POINT_WEIGHTS.get(event_type, 0))

    def threshold(self, key: str) -> float:
        thresholds = self.alert_thresholds or {}
        if key in thresholds:
            return float(thresholds[key])
        return float(DEFAULT_ALERT_THRESHOLDS[key])
