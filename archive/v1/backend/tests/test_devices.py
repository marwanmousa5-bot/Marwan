"""GPS device inventory: platform-only control, customer read-only view.

Section 4a item 2 and the Section 9 constraint that no customer role may ever
add, remove or reassign a device.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.enums import AuditAction, UserRole
from app.models.vehicle import Vehicle
from tests.conftest import auth, login, make_organization, make_user


@pytest.fixture
async def fixtures(client: AsyncClient, db: AsyncSession):
    org = await make_organization(db, "Acme Logistics")
    other = await make_organization(db, "Rival Freight")
    await make_user(db, email="root@fleetbeat.example.com", role=UserRole.SUPER_ADMIN)
    await make_user(
        db, email="admin@acme.example.com", role=UserRole.ORG_ADMIN, organization=org
    )
    vehicle = Vehicle(organization_id=org.id, name="Van 01", license_plate="ACM-001")
    foreign = Vehicle(
        organization_id=other.id, name="Rival Van", license_plate="RIV-001"
    )
    db.add_all([vehicle, foreign])
    await db.commit()

    return {
        "org": org,
        "other": other,
        "vehicle": vehicle,
        "foreign_vehicle": foreign,
        "root": await login(client, "root@fleetbeat.example.com"),
        "admin": await login(client, "admin@acme.example.com"),
    }


async def _add_device(client: AsyncClient, token: str, serial: str = "FB-0001") -> dict:
    response = await client.post(
        "/api/v1/platform-admin/devices",
        headers=auth(token),
        json={"serial_number": serial, "imei": f"IMEI{serial}", "model": "FB-Tracker 2"},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_device_enters_inventory_in_stock(client: AsyncClient, fixtures) -> None:
    device = await _add_device(client, fixtures["root"])
    assert device["status"] == "in_stock"
    assert device["organization_id"] is None
    assert device["vehicle_id"] is None


@pytest.mark.asyncio
async def test_duplicate_serial_is_rejected(client: AsyncClient, fixtures) -> None:
    await _add_device(client, fixtures["root"])
    duplicate = await client.post(
        "/api/v1/platform-admin/devices",
        headers=auth(fixtures["root"]),
        json={"serial_number": "FB-0001"},
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_assigning_a_device_makes_the_vehicle_tracked(
    client: AsyncClient, fixtures
) -> None:
    device = await _add_device(client, fixtures["root"])

    before = await client.get(
        f"/api/v1/vehicles/{fixtures['vehicle'].id}", headers=auth(fixtures["admin"])
    )
    assert before.json()["is_tracked"] is False
    assert before.json()["live_status"] == "not_tracked"

    assigned = await client.post(
        f"/api/v1/platform-admin/devices/{device['id']}/assign",
        headers=auth(fixtures["root"]),
        json={
            "organization_id": str(fixtures["org"].id),
            "vehicle_id": str(fixtures["vehicle"].id),
        },
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["status"] == "active"
    assert assigned.json()["vehicle_name"] == "Van 01"

    after = await client.get(
        f"/api/v1/vehicles/{fixtures['vehicle'].id}", headers=auth(fixtures["admin"])
    )
    assert after.json()["is_tracked"] is True
    # The customer can see the device, read-only.
    assert after.json()["device"]["serial_number"] == "FB-0001"


@pytest.mark.asyncio
async def test_device_cannot_be_assigned_to_another_orgs_vehicle(
    client: AsyncClient, fixtures
) -> None:
    device = await _add_device(client, fixtures["root"])
    response = await client.post(
        f"/api/v1/platform-admin/devices/{device['id']}/assign",
        headers=auth(fixtures["root"]),
        json={
            "organization_id": str(fixtures["org"].id),
            "vehicle_id": str(fixtures["foreign_vehicle"].id),
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_one_device_per_vehicle(client: AsyncClient, fixtures) -> None:
    first = await _add_device(client, fixtures["root"], "FB-0001")
    second = await _add_device(client, fixtures["root"], "FB-0002")
    body = {
        "organization_id": str(fixtures["org"].id),
        "vehicle_id": str(fixtures["vehicle"].id),
    }
    await client.post(
        f"/api/v1/platform-admin/devices/{first['id']}/assign",
        headers=auth(fixtures["root"]),
        json=body,
    )
    clash = await client.post(
        f"/api/v1/platform-admin/devices/{second['id']}/assign",
        headers=auth(fixtures["root"]),
        json=body,
    )
    assert clash.status_code == 409


@pytest.mark.asyncio
async def test_unassigning_returns_device_to_stock_and_untracks_vehicle(
    client: AsyncClient, fixtures
) -> None:
    device = await _add_device(client, fixtures["root"])
    await client.post(
        f"/api/v1/platform-admin/devices/{device['id']}/assign",
        headers=auth(fixtures["root"]),
        json={
            "organization_id": str(fixtures["org"].id),
            "vehicle_id": str(fixtures["vehicle"].id),
        },
    )
    unassigned = await client.post(
        f"/api/v1/platform-admin/devices/{device['id']}/unassign",
        headers=auth(fixtures["root"]),
    )
    assert unassigned.json()["status"] == "in_stock"
    assert unassigned.json()["vehicle_id"] is None

    vehicle = await client.get(
        f"/api/v1/vehicles/{fixtures['vehicle'].id}", headers=auth(fixtures["admin"])
    )
    assert vehicle.json()["is_tracked"] is False
    assert vehicle.json()["device"] is None


@pytest.mark.asyncio
async def test_marking_a_device_faulty_detaches_it(
    client: AsyncClient, fixtures
) -> None:
    device = await _add_device(client, fixtures["root"])
    await client.post(
        f"/api/v1/platform-admin/devices/{device['id']}/assign",
        headers=auth(fixtures["root"]),
        json={
            "organization_id": str(fixtures["org"].id),
            "vehicle_id": str(fixtures["vehicle"].id),
        },
    )
    faulty = await client.patch(
        f"/api/v1/platform-admin/devices/{device['id']}/status",
        headers=auth(fixtures["root"]),
        json={"status": "faulty", "notes": "No signal since install"},
    )
    assert faulty.json()["status"] == "faulty"
    assert faulty.json()["vehicle_id"] is None


@pytest.mark.asyncio
async def test_customers_cannot_touch_device_inventory(
    client: AsyncClient, fixtures
) -> None:
    """Section 9: device management is exclusively a super_admin action."""
    token = fixtures["admin"]
    device = await _add_device(client, fixtures["root"])

    assert (
        await client.get("/api/v1/platform-admin/devices", headers=auth(token))
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/platform-admin/devices",
            headers=auth(token),
            json={"serial_number": "SNEAKY-1"},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/platform-admin/devices/{device['id']}/assign",
            headers=auth(token),
            json={
                "organization_id": str(fixtures["org"].id),
                "vehicle_id": str(fixtures["vehicle"].id),
            },
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/platform-admin/devices/{device['id']}/unassign",
            headers=auth(token),
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_no_customer_facing_device_write_route_exists(
    client: AsyncClient,
) -> None:
    """Every device-mutating path must live under /platform-admin."""
    schema = (await client.get("/api/v1/openapi.json")).json()
    for path, operations in schema["paths"].items():
        if "device" not in path.lower():
            continue
        mutating = set(operations) - {"get"}
        if mutating:
            assert path.startswith("/api/v1/platform-admin/"), (
                f"{path} exposes {mutating} outside the Platform Admin Console"
            )


@pytest.mark.asyncio
async def test_assignment_is_audited(
    client: AsyncClient, fixtures, db: AsyncSession
) -> None:
    device = await _add_device(client, fixtures["root"])
    await client.post(
        f"/api/v1/platform-admin/devices/{device['id']}/assign",
        headers=auth(fixtures["root"]),
        json={
            "organization_id": str(fixtures["org"].id),
            "vehicle_id": str(fixtures["vehicle"].id),
        },
    )
    result = await db.execute(
        sa.select(AuditLog).where(
            AuditLog.action == AuditAction.DEVICE_ASSIGNED.value
        )
    )
    entries = list(result.scalars().all())
    assert len(entries) == 1
    assert entries[0].organization_id == fixtures["org"].id
    assert entries[0].actor_email == "root@fleetbeat.example.com"
