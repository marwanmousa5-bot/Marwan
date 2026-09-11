"""Auth, RBAC and the absence of public registration."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole, UserStatus
from tests.conftest import TEST_PASSWORD, auth, login, make_organization, make_user


@pytest.mark.asyncio
async def test_login_returns_tokens_and_org_context(
    client: AsyncClient, db: AsyncSession
) -> None:
    org = await make_organization(db, "Acme Logistics")
    await make_user(db, email="admin@acme.example.com", role=UserRole.ORG_ADMIN, organization=org)
    await db.commit()

    response = await client.post(
        "/api/v1/auth/login", json={"email": "admin@acme.example.com", "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["role"] == "org_admin"
    assert body["organization_name"] == "Acme Logistics"
    assert body["tokens"]["access_token"]
    assert body["tokens"]["refresh_token"]


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(client: AsyncClient, db: AsyncSession) -> None:
    org = await make_organization(db, "Acme Logistics")
    await make_user(db, email="admin@acme.example.com", role=UserRole.ORG_ADMIN, organization=org)
    await db.commit()

    response = await client.post(
        "/api/v1/auth/login", json={"email": "admin@acme.example.com", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_failed"


@pytest.mark.asyncio
async def test_pending_activation_user_cannot_log_in(
    client: AsyncClient, db: AsyncSession
) -> None:
    org = await make_organization(db, "Acme Logistics")
    await make_user(
        db,
        email="pending@acme.example.com",
        role=UserRole.DISPATCHER,
        organization=org,
        status=UserStatus.PENDING_ACTIVATION,
    )
    await db.commit()

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "pending@acme.example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 401
    assert "activated" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_no_public_registration_endpoint_exists(client: AsyncClient) -> None:
    """Section 9: there must be no way to self-register, at any path."""
    schema = (await client.get("/api/v1/openapi.json")).json()
    forbidden = ("register", "signup", "sign-up", "sign_up")
    offending = [
        path for path in schema["paths"] if any(word in path.lower() for word in forbidden)
    ]
    assert offending == [], f"Public registration route(s) present: {offending}"

    for path in ("/api/v1/auth/register", "/api/v1/auth/signup", "/api/v1/register"):
        assert (await client.post(path, json={})).status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_requests_are_rejected(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/vehicles")).status_code == 401
    assert (await client.get("/api/v1/platform-admin/overview")).status_code == 401


@pytest.mark.asyncio
async def test_org_user_cannot_reach_platform_admin_console(
    client: AsyncClient, db: AsyncSession
) -> None:
    org = await make_organization(db, "Acme Logistics")
    await make_user(db, email="admin@acme.example.com", role=UserRole.ORG_ADMIN, organization=org)
    await db.commit()
    token = await login(client, "admin@acme.example.com")

    for path in ("/api/v1/platform-admin/overview", "/api/v1/platform-admin/organizations"):
        response = await client.get(path, headers=auth(token))
        assert response.status_code == 403, path


@pytest.mark.asyncio
async def test_dispatcher_cannot_create_vehicles(
    client: AsyncClient, db: AsyncSession
) -> None:
    """RBAC is enforced at the dependency level, not just in the UI."""
    org = await make_organization(db, "Acme Logistics")
    await make_user(
        db, email="dispatch@acme.example.com", role=UserRole.DISPATCHER, organization=org
    )
    await db.commit()
    token = await login(client, "dispatch@acme.example.com")

    read = await client.get("/api/v1/vehicles", headers=auth(token))
    assert read.status_code == 200

    write = await client.post(
        "/api/v1/vehicles",
        headers=auth(token),
        json={"name": "Van 1", "license_plate": "AAA-111"},
    )
    assert write.status_code == 403


@pytest.mark.asyncio
async def test_driver_cannot_use_dashboard_endpoints(
    client: AsyncClient, db: AsyncSession
) -> None:
    org = await make_organization(db, "Acme Logistics")
    await make_user(db, email="driver@acme.example.com", role=UserRole.DRIVER, organization=org)
    await db.commit()
    token = await login(client, "driver@acme.example.com")

    assert (await client.get("/api/v1/vehicles", headers=auth(token))).status_code == 403
    assert (await client.get("/api/v1/drivers", headers=auth(token))).status_code == 403


@pytest.mark.asyncio
async def test_super_admin_has_no_tenant_scope(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Platform staff must impersonate to touch tenant data (Section 4a)."""
    await make_user(db, email="root@fleetbeat.example.com", role=UserRole.SUPER_ADMIN)
    await db.commit()
    token = await login(client, "root@fleetbeat.example.com")

    assert (await client.get("/api/v1/platform-admin/overview", headers=auth(token))).status_code == 200
    # No Organization context of their own -> tenant endpoints are refused.
    assert (await client.get("/api/v1/vehicles", headers=auth(token))).status_code == 403


@pytest.mark.asyncio
async def test_refresh_rotates_tokens_and_old_token_is_revoked(
    client: AsyncClient, db: AsyncSession
) -> None:
    org = await make_organization(db, "Acme Logistics")
    await make_user(db, email="admin@acme.example.com", role=UserRole.ORG_ADMIN, organization=org)
    await db.commit()

    login_response = await client.post(
        "/api/v1/auth/login", json={"email": "admin@acme.example.com", "password": TEST_PASSWORD}
    )
    refresh_token = login_response.json()["tokens"]["refresh_token"]

    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != refresh_token

    replayed = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert replayed.status_code == 401


@pytest.mark.asyncio
async def test_repeated_failures_lock_the_account(
    client: AsyncClient, db: AsyncSession
) -> None:
    org = await make_organization(db, "Acme Logistics")
    await make_user(db, email="admin@acme.example.com", role=UserRole.ORG_ADMIN, organization=org)
    await db.commit()

    for _ in range(5):
        await client.post(
            "/api/v1/auth/login", json={"email": "admin@acme.example.com", "password": "nope-nope-nope"}
        )

    response = await client.post(
        "/api/v1/auth/login", json={"email": "admin@acme.example.com", "password": TEST_PASSWORD}
    )
    assert response.status_code == 401
    assert "locked" in response.json()["detail"].lower()


def test_no_route_is_shadowed_by_an_earlier_one() -> None:
    """Guard against a whole class of routing bug.

    ``/drivers/{driver_id}`` registered before ``/drivers/scores`` silently
    swallows the literal route: the request reaches the parameterised handler
    and fails trying to parse "scores" as a UUID. Rather than reasoning about
    path shapes, this asks the real routing table the real question - would an
    earlier route match this route's own path, for a method they share?
    """
    from starlette.routing import Route

    from app.main import app

    routes = [
        route
        for route in app.routes
        if isinstance(route, Route) and getattr(route, "path_regex", None)
    ]

    shadowed: list[tuple[str, str, str]] = []
    for index, route in enumerate(routes):
        # Only a fully literal path can be swallowed by an earlier pattern.
        if "{" in route.path:
            continue
        for earlier in routes[:index]:
            if earlier.path == route.path or "{" not in earlier.path:
                continue
            if not earlier.path_regex.match(route.path):
                continue
            overlap = (earlier.methods or set()) & (route.methods or set())
            if overlap:
                shadowed.append((route.path, earlier.path, ", ".join(sorted(overlap))))

    assert shadowed == [], (
        "These routes are unreachable - an earlier parameterised route matches "
        f"them first: {shadowed}"
    )
