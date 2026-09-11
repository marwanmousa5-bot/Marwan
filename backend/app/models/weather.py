"""Cached adverse-weather zones used by the map overlay and delay alerts."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONB


class WeatherZone(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """A circular area with adverse conditions, refreshed from Open-Meteo."""

    __tablename__ = "weather_zones"

    latitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    longitude: Mapped[float] = mapped_column(sa.Float, nullable=False)
    radius_m: Mapped[float] = mapped_column(sa.Float, default=15000.0, nullable=False)
    condition: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    severity: Mapped[str] = mapped_column(sa.String(16), default="warning", nullable=False)
    expected_delay_minutes: Mapped[int] = mapped_column(
        sa.Integer, default=0, nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    raw: Mapped[dict | None] = mapped_column(JSONB)
