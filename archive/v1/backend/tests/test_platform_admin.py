"""Platform Admin Console: provisioning, suspension, impersonation, audit.

Section 4a - this is the only path by which an Organization and its first
Org Admin can exist.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.enums import AuditAction, UserRole, UserStatus
from tests.conftest import TEST_PASSWORD, auth, login, make_organization, make_user

PROVISION_PAYLOAD = {
    "name": "Northwind Transport",
    "industry": "Logistics",
    "timezone": "Europe/Amsterdam",
    "contact_name": "Ops Desk",
    "contact_email": "ops@northwind.example.com",
    "admin_full_name": "Nora Admin",
    "admin_email": "nora@northwind.example.com",
}


@pytest.fixture
async def platform_token(client: AsyncClient, db: AsyncSession) -> str:
    await make_user(db, email="root@fleetbeat.example.com", role=UserRole.SUPER_ADMIN)
    await db.commit()
    return await login(client, "root@fleetbeat.example.com")


@pytest.mark.asyncio
async def test_provisioning_creates_org_admin_and_activation_link(
    client: AsyncClient, platform_token: str
) -> None:
    response = await client.post(
        "/api/v1/platform-admin/organizations",
        headers=auth(platform_token),
        json=PROVISION_PAYLOAD,
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["organization"]["name"] == "Northwind Transport"
    assert body["organization"]["status"] == "active"
    assert body["admin_user"]["role"] == "org_admin"
    # The account exists but cannot be used until the link is consumed.
    assert body["admin_user"]["status"] == "pending_activation"
    # MVP: the link is displayed for manual delivery, not emailed.
    assert "/activate?token=" in body["activation_url"]


@pytest.mark.asyncio
async def test_provisioned_admin_can_activate_then_log_in(
    client: AsyncClient, platform_token: str
) -> None:
    provisioned = await client.post(
        "/api/v1/platform-admin/organizations",
        headers=auth(platform_token),
        json=PROVISION_PAYLOAD,
    )
    token = provisioned.json()["activation_url"].split("token=")[1]

    # Cannot log in before activation.
    before = await client.post(
        "/api/v1/auth/login",
        json={"email": "nora@northwind.example.com", "password": TEST_PASSWORD},
    )
    assert before.status_code == 401

    activated = await client.post(
        "/api/v1/auth/activate", json={"token": token, "password": "NorthWind!2026x"}
    )
    assert activated.status_code == 200

    after = await client.post(
        "/api/v1/auth/login",
        json={"email": "nora@northwind.example.com", "password": "NorthWind!2026x"},
    )
    assert after.status_code == 200
    assert after.json()["organization_name"] == "Northwind Transport"


@pytest.mark.asyncio
async def test_activation_link_is_single_use(
    client: AsyncClient, platform_token: str
) -> None:
    provisioned = await client.post(
        "/api/v1/platform-admin/organizations",
        headers=auth(platform_token),
        json=PROVISION_PAYLOAD,
    )
    token = provisioned.json()["activation_url"].split("token=")[1]

    first = await client.post(
        "/api/v1/auth/activate", json={"token": token, "password": "NorthWind!2026x"}
    )
    assert first.status_code == 200

    replay = await client.post(
        "/api/v1/auth/activate", json={"token": token, "password": "Different!2026x"}
    )
    assert replay.status_code == 404


@pytest.mark.asyncio
async def test_weak_activation_password_is_rejected(
    client: AsyncClient, platform_token: str
) -> None:
    provisioned = await client.post(
        "/api/v1/platform-admin/organizations",
        headers=auth(platform_token),
        json=PROVISION_PAYLOAD,
    )
    token = provisioned.json()["activation_url"].split("token=")[1]

    response = await client.post(
        "/api/v1/auth/activate", json={"token": token, "password": "alllowercase123"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_admin_email_is_rejected(
    client: AsyncClient, platform_token: str
) -> None:
    await client.post(
        "/api/v1/platform-admin/organizations",
        headers=auth(platform_token),
        json=PROVISION_PAYLOAD,
    )
    duplicate = await client.post(
        "/api/v1/platform-admin/organizations",
        headers=auth(platform_token),
        json={**PROVISION_PAYLOAD, "name": "Another Co"},
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_suspending_an_organization_blocks_its_logins(
    client: AsyncClient, platform_token: str
) -> None:
    provisioned = await client.post(
        "/api/v1/platform-admin/organizations",
        headers=auth(platform_token),
        json=PROVISION_PAYLOAD,
    )
    org_id = provisioned.json()["organization"]["id"]
    token = provisioned.json()["activation_url"].split("token=")[1]
    await client.post(
        "/api/v1/auth/activate", json={"token": token, "password": "NorthWind!2026x"}
    )

    suspended = await client.post(
        f"/api/v1/platform-admin/organizations/{org_id}/suspend",
        headers=auth(platform_token),
    )
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"

    blocked = await client.post(
        "/api/v1/auth/login",
        json={"email": "nora@northwind.example.com", "password": "NorthWind!2026x"},
    )
    assert blocked.status_code == 401

    await client.post(
        f"/api/v1/platform-admin/organizations/{org_id}/reactivate",
        headers=auth(platform_token),
    )
    allowed = await client.post(
        "/api/v1/auth/login",
        json={"email": "nora@northwind.example.com", "password": "NorthWind!2026x"},
    )
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_impersonation_grants_org_scope_and_is_audited(
    client: AsyncClient, platform_token: str, db: AsyncSession
) -> None:
    provisioned = await client.post(
        "/api/v1/platform-admin/organizations",
        headers=auth(platform_token),
        json=PROVISION_PAYLOAD,
    )
    org_id = provisioned.json()["organization"]["id"]
    activation = provisioned.json()["activation_url"].split("token=")[1]
    await client.post(
        "/api/v1/auth/activate",
        json={"token": activation, "password": "NorthWind!2026x"},
    )

    impersonation = await client.post(
        f"/api/v1/platform-admin/organizations/{org_id}/impersonate",
        headers=auth(platform_token),
    )
    assert impersonation.status_code == 200
    support_token = impersonation.json()["tokens"]["access_token"]

    # The impersonated session behaves exactly like that Org Admin...
    vehicles = await client.get("/api/v1/vehicles", headers=auth(support_token))
    assert vehicles.status_code == 200
    # ...and the session reports that it is an impersonation.
    me = await client.get("/api/v1/auth/me", headers=auth(support_token))
    assert me.json()["is_impersonating"] is True

    result = await db.execute(
        sa.select(AuditLog).where(
            AuditLog.action == AuditAction.IMPERSONATION_STARTED.value
        )
    )
    events = list(result.scalars().all())
    assert len(events) == 1
    assert events[0].actor_email == "root@fleetbeat.example.com"


@pytest.mark.asyncio
async def test_platform_overview_counts(client: AsyncClient, platform_token: str) -> None:
    await client.post(
        "/api/v1/platform-admin/organizations",
        headers=auth(platform_token),
        json=PROVISION_PAYLOAD,
    )
    response = await client.get(
        "/api/v1/platform-admin/overview", headers=auth(platform_token)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_organizations"] == 1
    assert body["active_organizations"] == 1
    assert body["total_vehicles"] == 0
    assert body["active_devices"] == 0


@pytest.mark.asyncio
async def test_organization_list_reports_health_indicators(
    client: AsyncClient, platform_token: str
) -> None:
    await client.post(
        "/api/v1/platform-admin/organizations",
        headers=auth(platform_token),
        json=PROVISION_PAYLOAD,
    )
    response = await client.get(
        "/api/v1/platform-admin/organizations", headers=auth(platform_token)
    )
    assert response.status_code == 200
    row = response.json()[0]
    assert row["organization"]["name"] == "Northwind Transport"
    assert row["vehicle_count"] == 0
    assert row["user_count"] == 1


@pytest.mark.asyncio
async def test_org_admin_can_only_invite_dispatchers_and_drivers(
    client: AsyncClient, db: AsyncSession
) -> None:
    org = await make_organization(db, "Acme Logistics")
    await make_user(
        db, email="admin@acme.example.com", role=UserRole.ORG_ADMIN, organization=org
    )
    await db.commit()
    token = await login(client, "admin@acme.example.com")

    ok = await client.post(
        "/api/v1/organization/users",
        headers=auth(token),
        json={
            "email": "dispatch@acme.example.com",
            "full_name": "Dana Dispatch",
            "role": "dispatcher",
        },
    )
    assert ok.status_code == 201
    assert "/activate?token=" in ok.json()["activation_url"]
    assert ok.json()["user"]["status"] == "pending_activation"

    # Cannot mint another Org Admin, and certainly not platform staff.
    for role in ("org_admin", "super_admin"):
        blocked = await client.post(
            "/api/v1/organization/users",
            headers=auth(token),
            json={
                "email": f"{role}@acme.example.com",
                "full_name": "Should Fail",
                "role": role,
            },
        )
        assert blocked.status_code == 403, role


@pytest.mark.asyncio
async def test_inviting_a_driver_creates_a_driver_profile(
    client: AsyncClient, db: AsyncSession
) -> None:
    org = await make_organization(db, "Acme Logistics")
    await make_user(
        db, email="admin@acme.example.com", role=UserRole.ORG_ADMIN, organization=org
    )
    await db.commit()
    token = await login(client, "admin@acme.example.com")

    await client.post(
        "/api/v1/organization/users",
        headers=auth(token),
        json={
            "email": "dee@acme.example.com",
            "full_name": "Dee Driver",
            "role": "driver",
        },
    )
    drivers = await client.get("/api/v1/drivers", headers=auth(token))
    assert drivers.json()["total"] == 1
    assert drivers.json()["items"][0]["full_name"] == "Dee Driver"


@pytest.mark.asyncio
async def test_reissued_activation_link_reactivates_a_locked_out_admin(
    client: AsyncClient, platform_token: str, db: AsyncSession
) -> None:
    provisioned = await client.post(
        "/api/v1/platform-admin/organizations",
        headers=auth(platform_token),
        json=PROVISION_PAYLOAD,
    )
    admin_id = provisioned.json()["admin_user"]["id"]

    response = await client.post(
        f"/api/v1/platform-admin/users/{admin_id}/activation-link",
        headers=auth(platform_token),
    )
    assert response.status_code == 200
    assert response.json()["user"]["status"] == UserStatus.PENDING_ACTIVATION.value
    assert "/activate?token=" in response.json()["activation_url"]


@pytest.mark.asyncio
async def test_an_invited_dispatcher_can_activate_and_sign_in(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The whole round trip the Settings screen exposes.

    There was already a test that an invite is created and one that a pending
    user cannot log in; nothing covered the step in between, which is the one
    an admin actually performs by hand because there is no email provider.
    """
    org = await make_organization(db, "Acme Logistics")
    await make_user(
        db, email="admin@acme.example.com", role=UserRole.ORG_ADMIN, organization=org
    )
    await db.commit()
    admin_token = await login(client, "admin@acme.example.com")

    invited = await client.post(
        "/api/v1/organization/users",
        headers=auth(admin_token),
        json={
            "email": "newdispatch@acme.example.com",
            "full_name": "New Dispatch",
            "role": "dispatcher",
        },
    )
    assert invited.status_code == 201
    token = invited.json()["activation_url"].split("token=")[1]

    activated = await client.post(
        "/api/v1/auth/activate",
        json={"token": token, "password": "BrandNewPassw0rd!2026"},
    )
    assert activated.status_code == 200

    signed_in = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "newdispatch@acme.example.com",
            "password": "BrandNewPassw0rd!2026",
        },
    )
    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["role"] == "dispatcher"
    assert signed_in.json()["user"]["status"] == "active"

    # The link is single-use, so a leaked one cannot be replayed.
    replay = await client.post(
        "/api/v1/auth/activate",
        json={"token": token, "password": "AnotherPassw0rd!2026"},
    )
    assert replay.status_code in (400, 404, 422)

    # And they still cannot change settings - the screen is read-only for them
    # because the API says so, not because the UI hides a button.
    dispatcher_token = signed_in.json()["tokens"]["access_token"]
    refused = await client.patch(
        "/api/v1/organization/settings",
        headers=auth(dispatcher_token),
        json={"driver_points_baseline": 9999},
    )
    assert refused.status_code == 403
