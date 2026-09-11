"""Tenant isolation - a security requirement, not a nice-to-have (Section 7).

These tests prove that Organization A can never read or write Organization
B's data through any endpoint, and that the isolation comes from the
authenticated principal rather than from anything the client sends.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import TenantScope
from app.models.audit import AuditLog
from app.models.driver import Driver
from app.models.enums import UserRole
from app.models.vehicle import Vehicle
from tests.conftest import auth, login, make_organization, make_user


@pytest.fixture
async def two_orgs(db: AsyncSession):
    """Two fully independent tenants, each with an admin and one vehicle."""
    org_a = await make_organization(db, "Alpha Freight")
    org_b = await make_organization(db, "Bravo Haulage")

    await make_user(
        db, email="admin@alpha.example.com", role=UserRole.ORG_ADMIN, organization=org_a
    )
    await make_user(
        db, email="admin@bravo.example.com", role=UserRole.ORG_ADMIN, organization=org_b
    )

    vehicle_a = Vehicle(
        organization_id=org_a.id, name="Alpha Van", license_plate="ALP-001"
    )
    vehicle_b = Vehicle(
        organization_id=org_b.id, name="Bravo Truck", license_plate="BRV-001"
    )
    driver_b = Driver(organization_id=org_b.id, full_name="Bravo Driver")
    db.add_all([vehicle_a, vehicle_b, driver_b])
    await db.commit()
    return {
        "org_a": org_a,
        "org_b": org_b,
        "vehicle_a": vehicle_a,
        "vehicle_b": vehicle_b,
        "driver_b": driver_b,
    }


@pytest.mark.asyncio
async def test_vehicle_list_only_returns_own_organization(
    client: AsyncClient, two_orgs
) -> None:
    token = await login(client, "admin@alpha.example.com")
    response = await client.get("/api/v1/vehicles", headers=auth(token))
    assert response.status_code == 200

    plates = {v["license_plate"] for v in response.json()["items"]}
    assert plates == {"ALP-001"}
    assert "BRV-001" not in plates


@pytest.mark.asyncio
async def test_cannot_read_another_orgs_vehicle_by_id(
    client: AsyncClient, two_orgs
) -> None:
    token = await login(client, "admin@alpha.example.com")
    foreign_id = two_orgs["vehicle_b"].id

    response = await client.get(f"/api/v1/vehicles/{foreign_id}", headers=auth(token))
    # 404, not 403: cross-tenant probing must not confirm that a row exists.
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cannot_update_another_orgs_vehicle(client: AsyncClient, two_orgs) -> None:
    token = await login(client, "admin@alpha.example.com")
    foreign_id = two_orgs["vehicle_b"].id

    response = await client.patch(
        f"/api/v1/vehicles/{foreign_id}", headers=auth(token), json={"name": "Hijacked"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cannot_retire_another_orgs_vehicle(client: AsyncClient, two_orgs) -> None:
    token = await login(client, "admin@alpha.example.com")
    response = await client.delete(
        f"/api/v1/vehicles/{two_orgs['vehicle_b'].id}", headers=auth(token)
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cannot_read_another_orgs_driver(client: AsyncClient, two_orgs) -> None:
    token = await login(client, "admin@alpha.example.com")
    response = await client.get(
        f"/api/v1/drivers/{two_orgs['driver_b'].id}", headers=auth(token)
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cannot_assign_another_orgs_driver_to_own_vehicle(
    client: AsyncClient, two_orgs
) -> None:
    """A foreign FK supplied in a body must be rejected, not silently stored."""
    token = await login(client, "admin@alpha.example.com")
    response = await client.post(
        "/api/v1/vehicles",
        headers=auth(token),
        json={
            "name": "Alpha Van 2",
            "license_plate": "ALP-002",
            "primary_driver_id": str(two_orgs["driver_b"].id),
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_client_supplied_organization_id_is_ignored(
    client: AsyncClient, two_orgs
) -> None:
    """Tenant scope comes from the JWT - never from the request body."""
    token = await login(client, "admin@alpha.example.com")
    response = await client.post(
        "/api/v1/vehicles",
        headers=auth(token),
        json={
            "name": "Smuggled Van",
            "license_plate": "ALP-003",
            "organization_id": str(two_orgs["org_b"].id),
        },
    )
    assert response.status_code == 201
    assert response.json()["organization_id"] == str(two_orgs["org_a"].id)


@pytest.mark.asyncio
async def test_organization_profile_is_always_the_callers_own(
    client: AsyncClient, two_orgs
) -> None:
    token = await login(client, "admin@bravo.example.com")
    response = await client.get("/api/v1/organization", headers=auth(token))
    assert response.status_code == 200
    assert response.json()["id"] == str(two_orgs["org_b"].id)


@pytest.mark.asyncio
async def test_org_admin_cannot_list_another_orgs_users(
    client: AsyncClient, two_orgs
) -> None:
    token = await login(client, "admin@alpha.example.com")
    response = await client.get("/api/v1/organization/users", headers=auth(token))
    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert emails == {"admin@alpha.example.com"}


@pytest.mark.asyncio
async def test_org_admin_cannot_suspend_another_orgs_user(
    client: AsyncClient, two_orgs, db: AsyncSession
) -> None:
    result = await db.execute(
        sa.select(sa.literal_column("id")).select_from(sa.text("users")).where(
            sa.text("email = 'admin@bravo.example.com'")
        )
    )
    foreign_user_id = result.scalar_one()

    token = await login(client, "admin@alpha.example.com")
    response = await client.post(
        f"/api/v1/organization/users/{foreign_user_id}/suspend", headers=auth(token)
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_audit_entries_are_written_to_the_actors_organization(
    client: AsyncClient, two_orgs, db: AsyncSession
) -> None:
    token = await login(client, "admin@alpha.example.com")
    await client.post(
        "/api/v1/vehicles",
        headers=auth(token),
        json={"name": "Audited Van", "license_plate": "ALP-009"},
    )

    result = await db.execute(
        sa.select(AuditLog).where(AuditLog.entity_type == "vehicle")
    )
    entries = list(result.scalars().all())
    assert entries, "vehicle creation must be audited"
    assert all(e.organization_id == two_orgs["org_a"].id for e in entries)


@pytest.mark.asyncio
async def test_tenant_scope_refuses_non_tenant_scoped_models(db: AsyncSession) -> None:
    """The scoping helper cannot be pointed at a table with no tenant column."""
    from app.core.errors import PermissionDeniedError
    from app.models.device import Device

    scope = TenantScope(uuid.uuid4())
    with pytest.raises(PermissionDeniedError):
        scope.select(Device)


@pytest.mark.asyncio
async def test_scope_get_returns_none_across_tenants(db: AsyncSession, two_orgs) -> None:
    scope_a = TenantScope(two_orgs["org_a"].id)
    assert await scope_a.get(db, Vehicle, two_orgs["vehicle_a"].id) is not None
    assert await scope_a.get(db, Vehicle, two_orgs["vehicle_b"].id) is None
