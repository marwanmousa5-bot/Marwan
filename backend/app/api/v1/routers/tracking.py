"""Live tracking, trip history and the WebSocket feed (Sections 4b, 4c)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta

import jwt
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal, get_tenant_scope, require_dashboard_user
from app.core.errors import NotFoundError
from app.core.security import decode_token
from app.core.tenancy import TenantScope
from app.db.session import SessionLocal, get_db
from app.models.alert import Alert
from app.models.device import Device
from app.models.driver import Driver, DriverEvent
from app.models.enums import (
    AlertStatus,
    DeviceStatus,
    OrganizationStatus,
    UserRole,
    UserStatus,
    VehicleLiveStatus,
)
from app.models.organization import Organization
from app.models.tracking import PositionSample, Trip
from app.models.user import User
from app.models.vehicle import Vehicle
from app.realtime.hub import hub
from app.schemas.common import Page
from app.schemas.tracking import (
    LiveKpis,
    LiveSnapshot,
    LiveVehicle,
    TripEventMarker,
    TripOut,
    TripPlayback,
    TripPoint,
)
from app.services.vehicles import MOVING_SPEED_THRESHOLD_KPH

router = APIRouter(tags=["tracking"])

#: A vehicle whose device has been silent longer than this is not "live",
#: even though its last known position is still worth showing on the map.
STALE_AFTER = timedelta(minutes=10)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@router.get(
    "/live/snapshot",
    response_model=LiveSnapshot,
    summary="Everything the Live Tracking page needs on first paint",
)
async def live_snapshot(
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> LiveSnapshot:
    now = datetime.now(UTC)

    rows = await db.execute(
        sa.select(Vehicle, Device)
        .outerjoin(Device, Device.vehicle_id == Vehicle.id)
        .where(Vehicle.organization_id == scope.organization_id)
        .order_by(Vehicle.name)
    )
    pairs = rows.all()

    alert_counts = dict(
        (
            await db.execute(
                sa.select(Alert.vehicle_id, sa.func.count())
                .where(
                    Alert.organization_id == scope.organization_id,
                    Alert.status == AlertStatus.ACTIVE,
                    Alert.vehicle_id.is_not(None),
                )
                .group_by(Alert.vehicle_id)
            )
        ).all()
    )
    total_active_alerts = int(
        (
            await db.execute(
                sa.select(sa.func.count()).where(
                    Alert.organization_id == scope.organization_id,
                    Alert.status == AlertStatus.ACTIVE,
                )
            )
        ).scalar_one()
    )

    driver_rows = await db.execute(
        sa.select(Driver.id, Driver.full_name, Driver.assigned_vehicle_id).where(
            Driver.organization_id == scope.organization_id,
            Driver.assigned_vehicle_id.is_not(None),
        )
    )
    drivers = {row[2]: (row[0], row[1]) for row in driver_rows.all()}

    # Today's distance, in the organization's own day boundary. UTC is an
    # acceptable approximation for MVP; per-org timezone handling belongs
    # with the analytics work in Phase 4.
    midnight = datetime.combine(now.date(), time.min, tzinfo=UTC)
    distance_today = float(
        (
            await db.execute(
                sa.select(sa.func.coalesce(sa.func.sum(Trip.distance_km), 0.0)).where(
                    Trip.organization_id == scope.organization_id,
                    Trip.started_at >= midnight,
                )
            )
        ).scalar_one()
    )

    vehicles: list[LiveVehicle] = []
    moving = idle = not_tracked = 0

    for vehicle, device in pairs:
        is_live_device = device is not None and device.status == DeviceStatus.ACTIVE
        last_seen = _aware(vehicle.last_position_at)
        fresh = last_seen is not None and (now - last_seen) < STALE_AFTER
        alert_count = int(alert_counts.get(vehicle.id, 0))

        if not is_live_device:
            status = VehicleLiveStatus.NOT_TRACKED
            not_tracked += 1
        elif alert_count > 0:
            status = VehicleLiveStatus.ALERT
            # An alerting vehicle is still either moving or stopped; count it
            # under whichever it is, so the KPI totals stay reconcilable.
            if fresh and (vehicle.last_speed_kph or 0) > MOVING_SPEED_THRESHOLD_KPH:
                moving += 1
            else:
                idle += 1
        elif fresh and (vehicle.last_speed_kph or 0) > MOVING_SPEED_THRESHOLD_KPH:
            status = VehicleLiveStatus.MOVING
            moving += 1
        else:
            status = VehicleLiveStatus.IDLE
            idle += 1

        driver = drivers.get(vehicle.id)
        vehicles.append(
            LiveVehicle(
                id=vehicle.id,
                name=vehicle.name,
                license_plate=vehicle.license_plate,
                live_status=status,
                latitude=vehicle.last_latitude,
                longitude=vehicle.last_longitude,
                heading=vehicle.last_heading,
                speed_kph=vehicle.last_speed_kph,
                last_position_at=last_seen,
                stopped_since=_aware(vehicle.stopped_since),
                is_tracked=is_live_device,
                device_serial=device.serial_number if device else None,
                device_last_signal_at=_aware(device.last_signal_at) if device else None,
                driver_id=driver[0] if driver else None,
                driver_name=driver[1] if driver else None,
                active_alert_count=alert_count,
            )
        )

    return LiveSnapshot(
        vehicles=vehicles,
        kpis=LiveKpis(
            total_vehicles=len(vehicles),
            active_now=moving,
            idle=idle,
            not_tracked=not_tracked,
            active_alerts=total_active_alerts,
            distance_today_km=round(distance_today, 1),
        ),
        server_time=now,
    )


@router.get("/trips", response_model=Page[TripOut], summary="Completed trips")
async def list_trips(
    vehicle_id: uuid.UUID | None = Query(default=None),
    driver_id: uuid.UUID | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Page[TripOut]:
    stmt = scope.select(Trip)
    if vehicle_id is not None:
        stmt = stmt.where(Trip.vehicle_id == vehicle_id)
    if driver_id is not None:
        stmt = stmt.where(Trip.driver_id == driver_id)
    if date_from is not None:
        stmt = stmt.where(
            Trip.started_at >= datetime.combine(date_from, time.min, tzinfo=UTC)
        )
    if date_to is not None:
        stmt = stmt.where(
            Trip.started_at
            < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
        )

    total = int(
        (await db.execute(sa.select(sa.func.count()).select_from(stmt.subquery())))
        .scalar_one()
    )
    result = await db.execute(
        stmt.order_by(Trip.started_at.desc()).limit(limit).offset(offset)
    )
    return Page[TripOut](
        items=[TripOut.model_validate(t) for t in result.scalars().all()],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/trips/{trip_id}/playback",
    response_model=TripPlayback,
    summary="Full recorded route plus event markers, for playback (Section 4c)",
)
async def trip_playback(
    trip_id: uuid.UUID,
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> TripPlayback:
    trip = await scope.get_or_404(db, Trip, trip_id, label="Trip")

    vehicle = await db.get(Vehicle, trip.vehicle_id)
    if vehicle is None:
        raise NotFoundError("Vehicle not found")

    driver_name: str | None = None
    if trip.driver_id:
        driver = await db.get(Driver, trip.driver_id)
        driver_name = driver.full_name if driver else None

    samples = await db.execute(
        sa.select(PositionSample)
        .where(PositionSample.trip_id == trip.id)
        .order_by(PositionSample.recorded_at)
    )
    points = [
        TripPoint(
            lat=s.latitude,
            lng=s.longitude,
            speed_kph=s.speed_kph,
            heading=s.heading,
            at=_aware(s.recorded_at) or datetime.now(UTC),
        )
        for s in samples.scalars().all()
    ]

    events = await db.execute(
        sa.select(DriverEvent)
        .where(DriverEvent.trip_id == trip.id)
        .order_by(DriverEvent.occurred_at)
    )
    markers = [
        TripEventMarker(
            id=e.id,
            event_type=e.event_type,
            severity=e.severity,
            at=_aware(e.occurred_at) or datetime.now(UTC),
            lat=e.latitude,
            lng=e.longitude,
            speed_kph=e.speed_kph,
        )
        for e in events.scalars().all()
    ]

    return TripPlayback(
        trip=TripOut.model_validate(trip),
        vehicle_name=vehicle.name,
        driver_name=driver_name,
        points=points,
        events=markers,
    )


# ---------------------------------------------------------------------------
# WebSocket feed
# ---------------------------------------------------------------------------

async def _authenticate_socket(token: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Resolve a socket's token to ``(user_id, organization_id)``.

    Browsers cannot set headers on a WebSocket handshake, so the access token
    arrives as a query parameter. It is the same signed access token the REST
    API requires - same expiry, same claims, same revocation on role change -
    and the Organization still comes from the token, never from the client.
    """
    try:
        payload = decode_token(token, expected_type="access")
    except jwt.PyJWTError:
        return None

    raw_user_id = payload.get("sub")
    raw_org_id = payload.get("org")
    if not raw_user_id or not raw_org_id:
        return None

    try:
        user_id = uuid.UUID(str(raw_user_id))
        organization_id = uuid.UUID(str(raw_org_id))
    except (TypeError, ValueError):
        return None

    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        if (
            user is None
            or user.status != UserStatus.ACTIVE
            or user.organization_id != organization_id
            or user.role not in {UserRole.ORG_ADMIN, UserRole.DISPATCHER}
        ):
            return None
        organization = await db.get(Organization, organization_id)
        if organization is None or organization.status != OrganizationStatus.ACTIVE:
            return None

    return user_id, organization_id


@router.websocket("/live/ws")
async def live_feed(websocket: WebSocket, token: str = Query(...)) -> None:
    """Per-Organization live feed: positions, trip transitions and alerts."""
    identity = await _authenticate_socket(token)
    if identity is None:
        # 1008 = policy violation; the handshake is rejected before accept.
        await websocket.close(code=1008)
        return

    _, organization_id = identity
    await hub.connect(organization_id, websocket)
    try:
        await websocket.send_json(
            {"type": "connected", "organization_id": str(organization_id)}
        )
        while True:
            # The feed is server-push only. Reading keeps the connection
            # alive and lets the client send heartbeats.
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(organization_id, websocket)
