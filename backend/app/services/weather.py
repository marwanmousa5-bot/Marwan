"""Adverse-weather zones and predicted-delay alerts (Section 4e).

Two jobs:

1. Refresh a small set of weather zones covering where each Organization's
   fleet actually is, for the map overlay.
2. Raise a predicted-delay alert when a live vehicle is inside one of those
   zones.

The linkage in step 2 is our own rule-based check, not an LLM guess - the AI
layer only ever phrases and ranks what this produces (Section 4e).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.weather import get_weather_client
from app.models.device import Device
from app.models.enums import (
    AlertRuleType,
    AlertSeverity,
    DeviceStatus,
    OrganizationStatus,
)
from app.models.organization import Organization
from app.models.vehicle import Vehicle
from app.models.weather import WeatherZone
from app.services import alerts as alert_service
from app.services import geo

#: Zones are refreshed every 30 minutes; expire them a little after that so a
#: stale overlay disappears rather than lingering as a wrong warning.
ZONE_TTL = timedelta(minutes=45)
#: Radius of the circular area one sampled point is taken to represent.
ZONE_RADIUS_M = 15_000.0
#: Sampling more than this per organization would hammer the free API for
#: very little extra fidelity at fleet scale.
MAX_SAMPLE_POINTS = 6


def utcnow() -> datetime:
    return datetime.now(UTC)


def _cluster(
    points: list[tuple[float, float]], *, radius_m: float = ZONE_RADIUS_M
) -> list[tuple[float, float]]:
    """Collapse nearby vehicle positions into a few representative samples."""
    clusters: list[list[tuple[float, float]]] = []
    for lat, lng in points:
        for cluster in clusters:
            head_lat, head_lng = cluster[0]
            if geo.haversine_m(lat, lng, head_lat, head_lng) <= radius_m:
                cluster.append((lat, lng))
                break
        else:
            clusters.append([(lat, lng)])

    centres = [geo.centroid(cluster) for cluster in clusters]
    return [c for c in centres if c is not None][:MAX_SAMPLE_POINTS]


async def refresh_zones_for_organization(
    db: AsyncSession, organization_id: uuid.UUID
) -> int:
    """Replace an Organization's weather zones with a fresh observation set."""
    rows = await db.execute(
        sa.select(Vehicle.last_latitude, Vehicle.last_longitude)
        .join(Device, Device.vehicle_id == Vehicle.id)
        .where(
            Vehicle.organization_id == organization_id,
            Device.status == DeviceStatus.ACTIVE,
            Vehicle.last_latitude.is_not(None),
            Vehicle.last_longitude.is_not(None),
        )
    )
    positions = [(float(r[0]), float(r[1])) for r in rows.all()]
    if not positions:
        return 0

    samples = _cluster(positions)
    observations = await get_weather_client().current(samples)

    now = utcnow()
    # Clear the previous set first: a zone that has cleared up must stop
    # being drawn, and merging would leave phantom storms on the map.
    await db.execute(
        sa.delete(WeatherZone).where(WeatherZone.organization_id == organization_id)
    )

    written = 0
    for observation in observations:
        if not observation.is_adverse:
            continue
        db.add(
            WeatherZone(
                organization_id=organization_id,
                latitude=observation.latitude,
                longitude=observation.longitude,
                radius_m=ZONE_RADIUS_M,
                condition=observation.condition,
                severity=observation.severity,
                expected_delay_minutes=observation.expected_delay_minutes,
                observed_at=now,
                expires_at=now + ZONE_TTL,
                raw={
                    "weather_code": observation.weather_code,
                    "temperature_c": observation.temperature_c,
                    "wind_kph": observation.wind_kph,
                    "precipitation_mm": observation.precipitation_mm,
                },
            )
        )
        written += 1

    await db.flush()
    return written


async def raise_weather_delay_alerts(
    db: AsyncSession, organization_id: uuid.UUID
) -> int:
    """Alert on live vehicles currently inside an adverse-weather zone."""
    zones = (
        await db.execute(
            sa.select(WeatherZone).where(
                WeatherZone.organization_id == organization_id
            )
        )
    ).scalars().all()
    if not zones:
        return 0

    rows = await db.execute(
        sa.select(Vehicle)
        .join(Device, Device.vehicle_id == Vehicle.id)
        .where(
            Vehicle.organization_id == organization_id,
            Device.status == DeviceStatus.ACTIVE,
            Vehicle.last_latitude.is_not(None),
            Vehicle.last_longitude.is_not(None),
        )
    )

    raised = 0
    for vehicle in rows.scalars().all():
        for zone in zones:
            inside = geo.point_in_circle(
                vehicle.last_latitude,
                vehicle.last_longitude,
                [zone.longitude, zone.latitude],
                zone.radius_m,
            )
            if not inside:
                continue

            label = zone.condition.replace("_", " ")
            alert = await alert_service.raise_alert(
                db,
                organization_id=organization_id,
                rule_type=AlertRuleType.WEATHER_DELAY,
                severity=(
                    AlertSeverity.WARNING
                    if zone.severity == "critical"
                    else AlertSeverity.INFO
                ),
                title=f"Predicted delay: {label}",
                message=(
                    f"{vehicle.name} is in an area of {label}. "
                    f"Expect roughly {zone.expected_delay_minutes} minutes of delay."
                ),
                vehicle_id=vehicle.id,
                subject_type="weather_zone",
                subject_id=zone.id,
                # One alert per vehicle per condition per hour: driving
                # through rain should not produce an alert every scan.
                dedupe_key=(
                    f"weather:{vehicle.id}:{zone.condition}:{utcnow():%Y%m%d%H}"
                ),
                context={
                    "condition": zone.condition,
                    "expected_delay_minutes": zone.expected_delay_minutes,
                },
            )
            if alert is not None:
                raised += 1
            break  # one zone is enough to explain the delay

    return raised


async def active_organization_ids(db: AsyncSession) -> list[uuid.UUID]:
    result = await db.execute(
        sa.select(Organization.id).where(
            Organization.status == OrganizationStatus.ACTIVE
        )
    )
    return [row[0] for row in result.all()]


async def expire_stale_zones(db: AsyncSession) -> int:
    result = await db.execute(
        sa.delete(WeatherZone).where(
            WeatherZone.expires_at.is_not(None), WeatherZone.expires_at < utcnow()
        )
    )
    return int(result.rowcount or 0)
