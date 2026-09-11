"""Map tools, alerts engine, maintenance, fuel and compliance (Phase 2)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import TenantScope
from app.models.alert import Alert
from app.models.enums import AlertRuleType, UserRole
from app.models.vehicle import Vehicle
from app.services import alerts as alert_service
from app.services import fuel as fuel_service
from app.services import maintenance as maintenance_service
from tests.conftest import auth, login, make_organization, make_user

AMSTERDAM_SQUARE = [[4.85, 52.34], [4.95, 52.34], [4.95, 52.40], [4.85, 52.40]]


@pytest.fixture
async def org_fixture(client: AsyncClient, db: AsyncSession):
    org = await make_organization(db, "Acme Logistics")
    await make_user(
        db, email="admin@acme.example.com", role=UserRole.ORG_ADMIN, organization=org
    )
    await make_user(
        db, email="dispatch@acme.example.com", role=UserRole.DISPATCHER, organization=org
    )
    vehicle = Vehicle(
        organization_id=org.id, name="Van 01", license_plate="ACM-001", odometer_km=50_000
    )
    db.add(vehicle)
    await db.commit()
    return {
        "org": org,
        "vehicle": vehicle,
        "admin": await login(client, "admin@acme.example.com"),
        "dispatcher": await login(client, "dispatch@acme.example.com"),
    }


# ---------------------------------------------------------------------------
# Geofences and POIs (Section 4d)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_polygon_geofence_round_trip(client: AsyncClient, org_fixture) -> None:
    created = await client.post(
        "/api/v1/geofences",
        headers=auth(org_fixture["admin"]),
        json={
            "name": "City centre",
            "shape": "polygon",
            "geometry": {"coordinates": AMSTERDAM_SQUARE},
            "color": "#FF6B35",
            "trigger": "both",
        },
    )
    assert created.status_code == 201, created.text
    assert len(created.json()["geometry"]["coordinates"]) == 4

    listed = await client.get("/api/v1/geofences", headers=auth(org_fixture["admin"]))
    assert len(listed.json()) == 1

    updated = await client.patch(
        f"/api/v1/geofences/{created.json()['id']}",
        headers=auth(org_fixture["admin"]),
        json={"is_active": False, "trigger": "on_enter"},
    )
    assert updated.json()["is_active"] is False
    assert updated.json()["trigger"] == "on_enter"

    deleted = await client.delete(
        f"/api/v1/geofences/{created.json()['id']}",
        headers=auth(org_fixture["admin"]),
    )
    assert deleted.status_code == 200
    assert (
        await client.get("/api/v1/geofences", headers=auth(org_fixture["admin"]))
    ).json() == []


@pytest.mark.asyncio
async def test_invalid_geofence_geometry_is_rejected(
    client: AsyncClient, org_fixture
) -> None:
    too_few = await client.post(
        "/api/v1/geofences",
        headers=auth(org_fixture["admin"]),
        json={
            "name": "Broken",
            "shape": "polygon",
            "geometry": {"coordinates": [[4.9, 52.3], [4.95, 52.3]]},
        },
    )
    assert too_few.status_code == 422

    no_radius = await client.post(
        "/api/v1/geofences",
        headers=auth(org_fixture["admin"]),
        json={
            "name": "Broken circle",
            "shape": "circle",
            "geometry": {"center": [4.9, 52.3]},
        },
    )
    assert no_radius.status_code == 422


@pytest.mark.asyncio
async def test_geofence_cannot_be_scoped_to_another_orgs_vehicle(
    client: AsyncClient, org_fixture, db: AsyncSession
) -> None:
    rival = await make_organization(db, "Rival Freight")
    foreign = Vehicle(
        organization_id=rival.id, name="Rival Van", license_plate="RIV-001"
    )
    db.add(foreign)
    await db.commit()

    response = await client.post(
        "/api/v1/geofences",
        headers=auth(org_fixture["admin"]),
        json={
            "name": "Sneaky",
            "shape": "circle",
            "geometry": {"center": [4.9, 52.3], "radius_m": 500},
            "vehicle_ids": [str(foreign.id)],
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_dispatcher_cannot_manage_geofences(
    client: AsyncClient, org_fixture
) -> None:
    """Drawing a fence changes what the whole org gets alerted on."""
    assert (
        await client.get("/api/v1/geofences", headers=auth(org_fixture["dispatcher"]))
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/geofences",
            headers=auth(org_fixture["dispatcher"]),
            json={
                "name": "Nope",
                "shape": "circle",
                "geometry": {"center": [4.9, 52.3], "radius_m": 500},
            },
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_poi_round_trip(client: AsyncClient, org_fixture) -> None:
    created = await client.post(
        "/api/v1/pois",
        headers=auth(org_fixture["dispatcher"]),
        json={
            "name": "Main depot",
            "category": "depot",
            "latitude": 52.3676,
            "longitude": 4.9041,
        },
    )
    assert created.status_code == 201
    assert created.json()["category"] == "depot"

    filtered = await client.get(
        "/api/v1/pois?category=fuel_station", headers=auth(org_fixture["admin"])
    )
    assert filtered.json() == []

    await client.delete(
        f"/api/v1/pois/{created.json()['id']}", headers=auth(org_fixture["admin"])
    )
    assert (await client.get("/api/v1/pois", headers=auth(org_fixture["admin"]))).json() == []


# ---------------------------------------------------------------------------
# Alerts engine (Section 4 item 12)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_alert_dedupe_and_rule_toggle(
    db: AsyncSession, org_fixture
) -> None:
    org = org_fixture["org"]

    first = await alert_service.raise_alert(
        db,
        organization_id=org.id,
        rule_type=AlertRuleType.MAINTENANCE_DUE,
        title="Service due",
        message="Oil change due",
        dedupe_key="svc-1",
    )
    assert first is not None

    # The same condition on the next scan must not create a second alert.
    assert (
        await alert_service.raise_alert(
            db,
            organization_id=org.id,
            rule_type=AlertRuleType.MAINTENANCE_DUE,
            title="Service due",
            message="Oil change due",
            dedupe_key="svc-1",
        )
        is None
    )

    rule = await alert_service.update_rule(
        db,
        TenantScope(org.id),
        rule_type=AlertRuleType.MAINTENANCE_DUE,
        is_enabled=False,
    )
    assert rule.is_enabled is False

    # A disabled rule raises nothing at all.
    assert (
        await alert_service.raise_alert(
            db,
            organization_id=org.id,
            rule_type=AlertRuleType.MAINTENANCE_DUE,
            title="Another",
            message="Another",
            dedupe_key="svc-2",
        )
        is None
    )


@pytest.mark.asyncio
async def test_maintenance_scan_raises_alerts_when_due(
    client: AsyncClient, db: AsyncSession, org_fixture
) -> None:
    org, vehicle = org_fixture["org"], org_fixture["vehicle"]

    created = await client.post(
        "/api/v1/maintenance/schedules",
        headers=auth(org_fixture["admin"]),
        json={
            "vehicle_id": str(vehicle.id),
            "name": "Oil change",
            "interval_type": "mileage",
            "interval_km": 10_000,
            "last_service_odometer_km": 45_000,
        },
    )
    assert created.status_code == 201, created.text
    # 45,000 + 10,000 = due at 55,000; the vehicle is at 50,000.
    assert created.json()["next_due_odometer_km"] == 55_000

    # Outside the 500 km warning window - nothing yet.
    assert await alert_service.scan_maintenance_due(db, org.id) == 0

    vehicle.odometer_km = 54_800
    await db.flush()
    assert await alert_service.scan_maintenance_due(db, org.id) == 1
    # Re-running the scan must not duplicate it.
    assert await alert_service.scan_maintenance_due(db, org.id) == 0
    await db.commit()

    alerts = await client.get("/api/v1/alerts", headers=auth(org_fixture["admin"]))
    assert alerts.json()["total"] == 1
    assert "Oil change" in alerts.json()["items"][0]["title"]


@pytest.mark.asyncio
async def test_document_expiry_scan(
    client: AsyncClient, db: AsyncSession, org_fixture
) -> None:
    org, vehicle = org_fixture["org"], org_fixture["vehicle"]

    soon = date.today() + timedelta(days=10)
    far = date.today() + timedelta(days=300)
    for title, expires in (("Insurance", soon), ("Registration", far)):
        response = await client.post(
            "/api/v1/compliance/documents",
            headers=auth(org_fixture["admin"]),
            json={
                "document_type": "insurance",
                "title": title,
                "vehicle_id": str(vehicle.id),
                "expires_on": expires.isoformat(),
            },
        )
        assert response.status_code == 201, response.text

    # Only the one inside the 30-day window alerts.
    assert await alert_service.scan_expiring_documents(db, org.id) == 1
    await db.commit()

    alerts = await client.get("/api/v1/alerts", headers=auth(org_fixture["admin"]))
    assert alerts.json()["total"] == 1
    assert "Insurance" in alerts.json()["items"][0]["title"]

    documents = await client.get(
        "/api/v1/compliance/documents", headers=auth(org_fixture["admin"])
    )
    by_title = {d["title"]: d for d in documents.json()["items"]}
    assert by_title["Insurance"]["days_until_expiry"] == 10


@pytest.mark.asyncio
async def test_expired_document_alerts_as_critical(
    db: AsyncSession, org_fixture, client: AsyncClient
) -> None:
    org, vehicle = org_fixture["org"], org_fixture["vehicle"]
    await client.post(
        "/api/v1/compliance/documents",
        headers=auth(org_fixture["admin"]),
        json={
            "document_type": "inspection",
            "title": "Annual inspection",
            "vehicle_id": str(vehicle.id),
            "expires_on": (date.today() - timedelta(days=3)).isoformat(),
        },
    )
    assert await alert_service.scan_expiring_documents(db, org.id) == 1
    await db.commit()

    alert = (await db.execute(sa.select(Alert))).scalar_one()
    assert alert.severity == "critical"
    assert "expired" in alert.title.lower()


@pytest.mark.asyncio
async def test_alert_acknowledge_and_resolve(
    client: AsyncClient, db: AsyncSession, org_fixture
) -> None:
    await alert_service.raise_alert(
        db,
        organization_id=org_fixture["org"].id,
        rule_type=AlertRuleType.SPEEDING,
        title="Speeding",
        message="138 km/h",
    )
    await db.commit()

    token = org_fixture["admin"]
    alert_id = (await client.get("/api/v1/alerts", headers=auth(token))).json()["items"][
        0
    ]["id"]

    acked = await client.post(
        f"/api/v1/alerts/{alert_id}/acknowledge", headers=auth(token)
    )
    assert acked.json()["status"] == "acknowledged"

    resolved = await client.post(
        f"/api/v1/alerts/{alert_id}/resolve", headers=auth(token)
    )
    assert resolved.json()["status"] == "resolved"

    # The default feed shows active alerts only.
    assert (await client.get("/api/v1/alerts", headers=auth(token))).json()["total"] == 0


# ---------------------------------------------------------------------------
# Maintenance work orders
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_completing_a_work_order_writes_history_and_advances_the_schedule(
    client: AsyncClient, org_fixture
) -> None:
    token = org_fixture["admin"]
    vehicle_id = str(org_fixture["vehicle"].id)

    schedule = (
        await client.post(
            "/api/v1/maintenance/schedules",
            headers=auth(token),
            json={
                "vehicle_id": vehicle_id,
                "name": "Oil change",
                "interval_type": "mileage",
                "interval_km": 10_000,
                "last_service_odometer_km": 45_000,
            },
        )
    ).json()
    assert schedule["next_due_odometer_km"] == 55_000

    work_order = (
        await client.post(
            "/api/v1/maintenance/work-orders",
            headers=auth(token),
            json={
                "vehicle_id": vehicle_id,
                "schedule_id": schedule["id"],
                "title": "Oil change",
            },
        )
    ).json()

    completed = await client.patch(
        f"/api/v1/maintenance/work-orders/{work_order['id']}",
        headers=auth(token),
        json={
            "status": "completed",
            "odometer_km": 55_200,
            "labour_cost": 80,
            "parts_cost": 45.5,
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["total_cost"] == 125.5
    assert completed.json()["completed_at"] is not None

    records = await client.get(
        "/api/v1/maintenance/service-records", headers=auth(token)
    )
    assert len(records.json()) == 1
    assert records.json()[0]["odometer_km"] == 55_200

    schedules = await client.get("/api/v1/maintenance/schedules", headers=auth(token))
    # The next service is now counted from the reading just recorded.
    assert schedules.json()[0]["next_due_odometer_km"] == 65_200


@pytest.mark.asyncio
async def test_time_based_schedule_computes_a_due_date(
    client: AsyncClient, org_fixture
) -> None:
    response = await client.post(
        "/api/v1/maintenance/schedules",
        headers=auth(org_fixture["admin"]),
        json={
            "vehicle_id": str(org_fixture["vehicle"].id),
            "name": "Annual service",
            "interval_type": "time",
            "interval_days": 365,
            "last_service_date": "2026-01-15",
        },
    )
    assert response.json()["next_due_date"] == "2027-01-15"


# ---------------------------------------------------------------------------
# Fuel & energy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fuel_log_derives_co2_and_updates_the_odometer(
    client: AsyncClient, org_fixture, db: AsyncSession
) -> None:
    token = org_fixture["admin"]
    response = await client.post(
        "/api/v1/fuel/logs",
        headers=auth(token),
        json={
            "vehicle_id": str(org_fixture["vehicle"].id),
            "fuel_type": "diesel",
            "quantity": 60,
            "unit": "L",
            "total_cost": 102.0,
            "odometer_km": 50_500,
            "filled_at": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    # 60 L diesel x 2.68 kg/L
    assert response.json()["co2_kg"] == pytest.approx(160.8)

    await db.refresh(org_fixture["vehicle"])
    assert org_fixture["vehicle"].odometer_km == 50_500


@pytest.mark.asyncio
async def test_fuel_summary_computes_consumption_over_logged_distance(
    client: AsyncClient, org_fixture
) -> None:
    token = org_fixture["admin"]
    now = datetime.now(UTC)
    for quantity, odometer, days_ago in ((50, 50_000, 20), (45, 50_500, 10)):
        await client.post(
            "/api/v1/fuel/logs",
            headers=auth(token),
            json={
                "vehicle_id": str(org_fixture["vehicle"].id),
                "fuel_type": "diesel",
                "quantity": quantity,
                "total_cost": quantity * 1.7,
                "odometer_km": odometer,
                "filled_at": (now - timedelta(days=days_ago)).isoformat(),
            },
        )

    summary = await client.get("/api/v1/fuel/summary", headers=auth(token))
    row = summary.json()[0]
    assert row["entries"] == 2
    assert row["total_quantity"] == 95
    # 95 L over the 500 km spanned by these entries.
    assert row["litres_per_100km"] == pytest.approx(19.0)


def test_co2_uses_org_overrides_when_present() -> None:
    assert fuel_service.co2_for(10, "diesel", None) == pytest.approx(26.8)
    assert fuel_service.co2_for(10, "diesel", {"diesel": 3.0}) == pytest.approx(30.0)
    # Electricity is deliberately zero unless an org supplies a grid factor.
    assert fuel_service.co2_for(50, "electric", None) == 0.0


def test_next_due_falls_back_to_current_odometer_for_a_new_schedule() -> None:
    """A new schedule on a high-mileage vehicle must not look overdue."""
    from app.models.maintenance import MaintenanceSchedule

    vehicle = Vehicle(name="V", license_plate="P", odometer_km=120_000)
    schedule = MaintenanceSchedule(
        name="Brakes", interval_type="mileage", interval_km=20_000
    )
    next_km, next_date = maintenance_service.compute_next_due(schedule, vehicle)
    assert next_km == 140_000
    assert next_date is None


# ---------------------------------------------------------------------------
# Compliance tenancy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_document_must_attach_to_a_vehicle_or_driver(
    client: AsyncClient, org_fixture
) -> None:
    response = await client.post(
        "/api/v1/compliance/documents",
        headers=auth(org_fixture["admin"]),
        json={"document_type": "other", "title": "Floating document"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_cannot_attach_a_document_to_another_orgs_vehicle(
    client: AsyncClient, org_fixture, db: AsyncSession
) -> None:
    rival = await make_organization(db, "Rival Freight")
    foreign = Vehicle(organization_id=rival.id, name="Rival", license_plate="RIV-9")
    db.add(foreign)
    await db.commit()

    response = await client.post(
        "/api/v1/compliance/documents",
        headers=auth(org_fixture["admin"]),
        json={
            "document_type": "insurance",
            "title": "Sneaky",
            "vehicle_id": str(foreign.id),
        },
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Momentary vs. standing alerts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_momentary_alerts_stop_colouring_a_vehicle_red(
    client: AsyncClient, db: AsyncSession, org_fixture
) -> None:
    """A speeding event from an hour ago must not pin a vehicle red.

    Without this the whole fleet turns red within an hour of the feed running
    and the status colour stops carrying any information.
    """
    from app.models.device import Device
    from app.models.enums import DeviceStatus

    org, vehicle = org_fixture["org"], org_fixture["vehicle"]
    db.add(
        Device(
            serial_number="FB-ALERT-1",
            status=DeviceStatus.ACTIVE,
            organization_id=org.id,
            vehicle_id=vehicle.id,
        )
    )
    vehicle.last_latitude = 52.3676
    vehicle.last_longitude = 4.9041
    vehicle.last_speed_kph = 0.0
    vehicle.last_position_at = datetime.now(UTC)
    await db.flush()

    alert = await alert_service.raise_alert(
        db,
        organization_id=org.id,
        rule_type=AlertRuleType.SPEEDING,
        title="Speeding",
        message="132 km/h",
        vehicle_id=vehicle.id,
    )
    assert alert is not None
    await db.commit()

    token = org_fixture["admin"]
    fresh = await client.get("/api/v1/live/snapshot", headers=auth(token))
    assert fresh.json()["vehicles"][0]["live_status"] == "alert"

    # Age it past the map window.
    alert.created_at = datetime.now(UTC) - timedelta(hours=1)
    await db.commit()

    aged = await client.get("/api/v1/live/snapshot", headers=auth(token))
    assert aged.json()["vehicles"][0]["live_status"] == "idle"
    # It is still in the feed - it just no longer demands attention.
    assert (await client.get("/api/v1/alerts", headers=auth(token))).json()["total"] == 1


@pytest.mark.asyncio
async def test_standing_alerts_keep_colouring_a_vehicle_red(
    client: AsyncClient, db: AsyncSession, org_fixture
) -> None:
    """A document that expired last week is still a problem today."""
    from app.models.device import Device
    from app.models.enums import DeviceStatus

    org, vehicle = org_fixture["org"], org_fixture["vehicle"]
    db.add(
        Device(
            serial_number="FB-ALERT-2",
            status=DeviceStatus.ACTIVE,
            organization_id=org.id,
            vehicle_id=vehicle.id,
        )
    )
    vehicle.last_position_at = datetime.now(UTC)
    await db.flush()

    alert = await alert_service.raise_alert(
        db,
        organization_id=org.id,
        rule_type=AlertRuleType.DOCUMENT_EXPIRING,
        title="Insurance expired",
        message="Expired 7 days ago",
        vehicle_id=vehicle.id,
    )
    assert alert is not None
    alert.created_at = datetime.now(UTC) - timedelta(days=3)
    await db.commit()

    snapshot = await client.get("/api/v1/live/snapshot", headers=auth(org_fixture["admin"]))
    assert snapshot.json()["vehicles"][0]["live_status"] == "alert"


@pytest.mark.asyncio
async def test_sweep_resolves_only_aged_momentary_alerts(
    db: AsyncSession, org_fixture
) -> None:
    org = org_fixture["org"]

    recent = await alert_service.raise_alert(
        db,
        organization_id=org.id,
        rule_type=AlertRuleType.HARSH_DRIVING,
        title="Harsh braking",
        message="-4.2 m/s2",
    )
    old = await alert_service.raise_alert(
        db,
        organization_id=org.id,
        rule_type=AlertRuleType.SPEEDING,
        title="Speeding",
        message="128 km/h",
        dedupe_key="old-speeding",
    )
    standing = await alert_service.raise_alert(
        db,
        organization_id=org.id,
        rule_type=AlertRuleType.MAINTENANCE_DUE,
        title="Service due",
        message="Overdue by 300 km",
    )
    assert recent and old and standing

    stale = datetime.now(UTC) - timedelta(hours=5)
    old.created_at = stale
    standing.created_at = stale
    await db.flush()

    assert await alert_service.auto_resolve_momentary_alerts(db) == 1
    await db.flush()
    await db.refresh(recent)
    await db.refresh(old)
    await db.refresh(standing)

    assert recent.status == "active", "a recent event is left alone"
    assert old.status == "resolved", "an aged momentary event is swept"
    assert standing.status == "active", "a standing condition is never swept"
