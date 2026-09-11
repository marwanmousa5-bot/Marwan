"""Vehicle and driver CRUD, org settings, and the audit write path."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.enums import UserRole
from app.models.organization import DEFAULT_POINT_WEIGHTS
from tests.conftest import auth, login, make_organization, make_user


@pytest.fixture
async def admin_token(client: AsyncClient, db: AsyncSession) -> str:
    org = await make_organization(db, "Acme Logistics")
    await make_user(
        db, email="admin@acme.example.com", role=UserRole.ORG_ADMIN, organization=org
    )
    await db.commit()
    return await login(client, "admin@acme.example.com")


@pytest.mark.asyncio
async def test_vehicle_crud_round_trip(client: AsyncClient, admin_token: str) -> None:
    created = await client.post(
        "/api/v1/vehicles",
        headers=auth(admin_token),
        json={
            "name": "Van 01",
            "make": "Ford",
            "model": "Transit",
            "year": 2023,
            "license_plate": "VAN-001",
            "vehicle_type": "van",
            "fuel_type": "diesel",
            "odometer_km": 12000,
        },
    )
    assert created.status_code == 201, created.text
    vehicle = created.json()
    assert vehicle["name"] == "Van 01"
    # No device has been assigned by platform staff yet (Section 4a).
    assert vehicle["is_tracked"] is False
    assert vehicle["live_status"] == "not_tracked"
    assert vehicle["device"] is None

    vehicle_id = vehicle["id"]
    updated = await client.patch(
        f"/api/v1/vehicles/{vehicle_id}",
        headers=auth(admin_token),
        json={"odometer_km": 12500, "status": "in_maintenance"},
    )
    assert updated.status_code == 200
    assert updated.json()["odometer_km"] == 12500
    assert updated.json()["status"] == "in_maintenance"

    retired = await client.delete(
        f"/api/v1/vehicles/{vehicle_id}", headers=auth(admin_token)
    )
    assert retired.json()["status"] == "retired"

    # Retired, not deleted - the record and its history survive.
    still_there = await client.get(
        f"/api/v1/vehicles/{vehicle_id}", headers=auth(admin_token)
    )
    assert still_there.status_code == 200


@pytest.mark.asyncio
async def test_duplicate_plate_within_org_is_rejected(
    client: AsyncClient, admin_token: str
) -> None:
    payload = {"name": "Van 01", "license_plate": "VAN-001"}
    assert (
        await client.post("/api/v1/vehicles", headers=auth(admin_token), json=payload)
    ).status_code == 201
    duplicate = await client.post(
        "/api/v1/vehicles", headers=auth(admin_token), json={**payload, "name": "Van 02"}
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_vehicle_search_and_filter(client: AsyncClient, admin_token: str) -> None:
    for name, plate, status in (
        ("Alpha Van", "AAA-1", "active"),
        ("Beta Truck", "BBB-2", "active"),
        ("Gamma Van", "CCC-3", "retired"),
    ):
        await client.post(
            "/api/v1/vehicles",
            headers=auth(admin_token),
            json={"name": name, "license_plate": plate, "status": status},
        )

    by_name = await client.get("/api/v1/vehicles?search=van", headers=auth(admin_token))
    assert {v["name"] for v in by_name.json()["items"]} == {"Alpha Van", "Gamma Van"}

    active = await client.get("/api/v1/vehicles?status=active", headers=auth(admin_token))
    assert active.json()["total"] == 2


@pytest.mark.asyncio
async def test_driver_crud_with_optional_mobile_login(
    client: AsyncClient, admin_token: str
) -> None:
    created = await client.post(
        "/api/v1/drivers",
        headers=auth(admin_token),
        json={
            "full_name": "Sam Driver",
            "license_number": "DL-99887",
            "license_expiry": "2029-05-01",
            "login_email": "sam@acme.example.com",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["driver"]["full_name"] == "Sam Driver"
    assert body["driver"]["points_balance"] == 100  # configurable baseline
    assert body["driver"]["safety_score"] == 100.0
    assert body["activation_url"] and "/activate?token=" in body["activation_url"]

    driver_id = body["driver"]["id"]
    updated = await client.patch(
        f"/api/v1/drivers/{driver_id}",
        headers=auth(admin_token),
        json={"employment_status": "on_leave"},
    )
    assert updated.json()["employment_status"] == "on_leave"

    terminated = await client.delete(
        f"/api/v1/drivers/{driver_id}", headers=auth(admin_token)
    )
    assert terminated.json()["employment_status"] == "terminated"


@pytest.mark.asyncio
async def test_driver_without_login_email_gets_no_activation_link(
    client: AsyncClient, admin_token: str
) -> None:
    created = await client.post(
        "/api/v1/drivers", headers=auth(admin_token), json={"full_name": "Profile Only"}
    )
    assert created.status_code == 201
    assert created.json()["activation_url"] is None


@pytest.mark.asyncio
async def test_point_weights_are_configurable_not_hardcoded(
    client: AsyncClient, admin_token: str
) -> None:
    """Section 4g / Section 9: penalty weights must be Org-Admin tunable."""
    defaults = await client.get("/api/v1/organization/settings", headers=auth(admin_token))
    assert defaults.status_code == 200
    assert defaults.json()["point_weights"] == DEFAULT_POINT_WEIGHTS
    assert defaults.json()["show_leaderboard_to_drivers"] is False
    assert defaults.json()["maintenance_auto_book_enabled"] is False

    tuned = await client.patch(
        "/api/v1/organization/settings",
        headers=auth(admin_token),
        json={"point_weights": {"speeding": -12}, "show_leaderboard_to_drivers": True},
    )
    assert tuned.status_code == 200
    weights = tuned.json()["point_weights"]
    assert weights["speeding"] == -12
    # A partial update merges rather than wiping the other weights.
    assert weights["harsh_braking"] == DEFAULT_POINT_WEIGHTS["harsh_braking"]
    assert tuned.json()["show_leaderboard_to_drivers"] is True


@pytest.mark.asyncio
async def test_dispatcher_cannot_change_org_settings(
    client: AsyncClient, db: AsyncSession
) -> None:
    org = await make_organization(db, "Acme Logistics")
    await make_user(
        db, email="dispatch@acme.example.com", role=UserRole.DISPATCHER, organization=org
    )
    await db.commit()
    token = await login(client, "dispatch@acme.example.com")

    assert (
        await client.get("/api/v1/organization/settings", headers=auth(token))
    ).status_code == 200
    assert (
        await client.patch(
            "/api/v1/organization/settings",
            headers=auth(token),
            json={"show_leaderboard_to_drivers": True},
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_updates_are_audited_with_a_before_after_diff(
    client: AsyncClient, admin_token: str, db: AsyncSession
) -> None:
    created = await client.post(
        "/api/v1/vehicles",
        headers=auth(admin_token),
        json={"name": "Van 01", "license_plate": "VAN-001", "odometer_km": 100},
    )
    vehicle_id = created.json()["id"]
    await client.patch(
        f"/api/v1/vehicles/{vehicle_id}",
        headers=auth(admin_token),
        json={"odometer_km": 450},
    )

    result = await db.execute(
        sa.select(AuditLog)
        .where(AuditLog.entity_type == "vehicle", AuditLog.action == "update")
        .order_by(AuditLog.created_at)
    )
    entry = list(result.scalars().all())[-1]
    assert entry.changes["before"]["odometer_km"] == 100.0
    assert entry.changes["after"]["odometer_km"] == 450.0
    assert entry.actor_email == "admin@acme.example.com"


@pytest.mark.asyncio
async def test_login_events_are_audited(
    client: AsyncClient, admin_token: str, db: AsyncSession
) -> None:
    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@acme.example.com", "password": "definitely-wrong"},
    )
    result = await db.execute(sa.select(AuditLog.action))
    actions = {row[0] for row in result.all()}
    assert "login_success" in actions
    assert "login_failure" in actions


@pytest.mark.asyncio
async def test_audit_log_has_no_mutating_api_surface(client: AsyncClient) -> None:
    """The audit log is append-only: nothing may edit or delete an entry."""
    schema = (await client.get("/api/v1/openapi.json")).json()
    for path, operations in schema["paths"].items():
        if "audit" in path.lower():
            assert set(operations) <= {"get"}, f"{path} exposes {set(operations)}"
