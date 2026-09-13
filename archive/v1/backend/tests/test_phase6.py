"""Phase 6: Exception Auto-Rerouting, the audit-log views and login activity.

The rerouting tests matter most. "Auto-rerouting" names the detection, not
the application - so these prove that detecting an obstruction changes
nothing, and that only an explicit, audited confirm moves a running task onto
a different route (Section 9).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import TenantScope
from app.integrations.osrm import (
    OsrmClient,
    RouteResult,
    RoutingUnavailableError,
    set_osrm_client,
)
from app.models.audit import AuditLog
from app.models.driver import Driver
from app.models.enums import AuditAction, TaskStatus, UserRole
from app.models.routing import RoadClosure, Route
from app.models.task import Task
from app.models.user import LoginAttempt
from app.models.vehicle import Vehicle
from app.services import geo, rerouting
from tests.conftest import auth, login, make_organization, make_user

# A straight line of vertices from the depot east through the closure point.
CLEAR_PATH = [(52.370, 4.890), (52.370, 4.900), (52.370, 4.910)]
DETOUR_PATH = [(52.370, 4.890), (52.380, 4.900), (52.370, 4.910)]


def encode(points: list[tuple[float, float]]) -> str:
    """Encode (lat, lng) pairs the way OSRM does, so the decoder is exercised."""
    output = []
    previous_lat = previous_lng = 0
    for lat, lng in points:
        for value, previous in (
            (round(lat * 1e5), previous_lat),
            (round(lng * 1e5), previous_lng),
        ):
            delta = value - previous
            delta = ~(delta << 1) if delta < 0 else delta << 1
            while delta >= 0x20:
                output.append(chr((0x20 | (delta & 0x1F)) + 63))
                delta >>= 5
            output.append(chr(delta + 63))
        previous_lat, previous_lng = round(lat * 1e5), round(lng * 1e5)
    return "".join(output)


class FakeOsrm(OsrmClient):
    """Returns the detour geometry and a longer, slower route."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.calls: list[list[tuple[float, float]]] = []

    async def route(self, coordinates, **kwargs) -> RouteResult:  # type: ignore[override]
        self.calls.append(list(coordinates))
        if not self.available:
            raise RoutingUnavailableError("The routing engine is not reachable")
        return RouteResult(
            distance_m=9_400.0,
            duration_s=1_020.0,
            geometry_polyline=encode(DETOUR_PATH),
        )


@pytest.fixture
def osrm():
    fake = FakeOsrm()
    set_osrm_client(fake)
    yield fake
    set_osrm_client(OsrmClient())


@pytest.fixture
async def routed_fleet(client: AsyncClient, db: AsyncSession):
    """A tenant with one task already en route, and a closure on its path."""
    org = await make_organization(db, "Delta Couriers")
    await make_user(
        db, email="admin@delta.example.com", role=UserRole.ORG_ADMIN, organization=org
    )
    await make_user(
        db,
        email="dispatch@delta.example.com",
        role=UserRole.DISPATCHER,
        organization=org,
    )

    vehicle = Vehicle(
        organization_id=org.id,
        name="Van 09",
        license_plate="DLT-009",
        last_latitude=52.370,
        last_longitude=4.890,
    )
    db.add(vehicle)
    await db.flush()
    driver = Driver(
        organization_id=org.id, full_name="Dana Driver", assigned_vehicle_id=vehicle.id
    )
    db.add(driver)
    await db.flush()

    task = Task(
        organization_id=org.id,
        title="Deliver to Oost",
        driver_id=driver.id,
        vehicle_id=vehicle.id,
        destination_latitude=52.370,
        destination_longitude=4.910,
        status=TaskStatus.EN_ROUTE,
    )
    db.add(task)
    await db.flush()

    route = Route(
        organization_id=org.id,
        task_id=task.id,
        vehicle_id=vehicle.id,
        driver_id=driver.id,
        origin_latitude=52.370,
        origin_longitude=4.890,
        destination_latitude=52.370,
        destination_longitude=4.910,
        distance_km=7.0,
        duration_seconds=780,
        geometry_polyline=encode(CLEAR_PATH),
        is_active=True,
    )
    db.add(route)
    await db.flush()
    task.route_id = route.id

    closure = RoadClosure(
        organization_id=org.id,
        label="Burgweg bridge works",
        latitude=52.370,
        longitude=4.900,  # Directly on the route's middle vertex.
        radius_m=400.0,
        is_active=True,
    )
    db.add(closure)
    await db.commit()

    return {
        "org": org,
        "scope": TenantScope(org.id),
        "vehicle": vehicle,
        "driver": driver,
        "task": task,
        "route": route,
        "closure": closure,
        "admin": await login(client, "admin@delta.example.com"),
        "dispatcher": await login(client, "dispatch@delta.example.com"),
    }


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detection_finds_a_closure_on_the_real_route_geometry(
    db: AsyncSession, routed_fleet
) -> None:
    hits = await rerouting.detect(db, routed_fleet["org"].id)
    assert len(hits) == 1
    task, route, obstruction = hits[0]
    assert task.id == routed_fleet["task"].id
    assert route.id == routed_fleet["route"].id
    assert obstruction.label == "Burgweg bridge works"


@pytest.mark.asyncio
async def test_a_closure_beside_the_route_is_not_a_hit(
    db: AsyncSession, routed_fleet
) -> None:
    """Detection is geometry, so it must not fire on anything merely nearby."""
    closure = routed_fleet["closure"]
    # ~5.5 km north of the path, well outside the 400 m radius.
    closure.latitude = 52.420
    await db.commit()

    assert await rerouting.detect(db, routed_fleet["org"].id) == []


@pytest.mark.asyncio
async def test_a_lifted_closure_stops_being_detected(
    db: AsyncSession, routed_fleet
) -> None:
    routed_fleet["closure"].is_active = False
    await db.commit()
    assert await rerouting.detect(db, routed_fleet["org"].id) == []


@pytest.mark.asyncio
async def test_an_expired_closure_window_stops_being_detected(
    db: AsyncSession, routed_fleet
) -> None:
    closure = routed_fleet["closure"]
    closure.active_until = datetime.now(UTC) - timedelta(hours=1)
    await db.commit()
    assert await rerouting.detect(db, routed_fleet["org"].id) == []


# ---------------------------------------------------------------------------
# The confirmation gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detecting_and_proposing_changes_nothing(
    client: AsyncClient, db: AsyncSession, routed_fleet, osrm
) -> None:
    """Section 9: an obstructed route is not silently swapped."""
    response = await client.get(
        "/api/v1/reroutes/proposals", headers=auth(routed_fleet["admin"])
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["obstruction_label"] == "Burgweg bridge works"
    assert body[0]["added_km"] == pytest.approx(2.4, abs=0.01)
    assert body[0]["routing_available"] is True

    # The task is still on its original route.
    await db.refresh(routed_fleet["task"])
    assert routed_fleet["task"].route_id == routed_fleet["route"].id
    await db.refresh(routed_fleet["route"])
    assert routed_fleet["route"].is_active is True

    routes = (
        await db.execute(
            sa.select(sa.func.count()).select_from(Route).where(
                Route.organization_id == routed_fleet["org"].id
            )
        )
    ).scalar_one()
    assert routes == 1, "proposing must not persist a second route"


@pytest.mark.asyncio
async def test_the_copilot_card_for_a_reroute_carries_an_apply_payload(
    client: AsyncClient, db: AsyncSession, routed_fleet, osrm
) -> None:
    response = await client.post(
        "/api/v1/copilot/run", headers=auth(routed_fleet["admin"])
    )
    assert response.status_code == 200
    cards = [c for c in response.json() if c["kind"] == "reroute"]
    assert len(cards) == 1
    assert cards[0]["action_payload"]["op"] == "apply_reroute"
    assert cards[0]["action_payload"]["task_id"] == str(routed_fleet["task"].id)

    # Still nothing applied.
    await db.refresh(routed_fleet["route"])
    assert routed_fleet["route"].is_active is True


@pytest.mark.asyncio
async def test_applying_switches_the_route_and_audits_it(
    client: AsyncClient, db: AsyncSession, routed_fleet, osrm
) -> None:
    cards = (
        await client.post("/api/v1/copilot/run", headers=auth(routed_fleet["admin"]))
    ).json()
    card = next(c for c in cards if c["kind"] == "reroute")

    response = await client.post(
        f"/api/v1/copilot/recommendations/{card['id']}/apply",
        headers=auth(routed_fleet["admin"]),
    )
    assert response.status_code == 200, response.text

    await db.refresh(routed_fleet["route"])
    assert routed_fleet["route"].is_active is False

    new_route = (
        await db.execute(
            sa.select(Route).where(
                Route.organization_id == routed_fleet["org"].id,
                Route.is_active.is_(True),
            )
        )
    ).scalar_one()
    assert new_route.replaced_route_id == routed_fleet["route"].id
    assert "Burgweg bridge works" in (new_route.reroute_reason or "")

    await db.refresh(routed_fleet["task"])
    assert routed_fleet["task"].route_id == new_route.id

    entry = (
        await db.execute(
            sa.select(AuditLog).where(AuditLog.action == AuditAction.ROUTE_REROUTED)
        )
    ).scalar_one()
    assert "Deliver to Oost" in (entry.summary or "")


@pytest.mark.asyncio
async def test_a_dispatcher_cannot_apply_a_reroute(
    client: AsyncClient, routed_fleet, osrm
) -> None:
    """Applying is an org_admin action, like every other confirmed change."""
    cards = (
        await client.post("/api/v1/copilot/run", headers=auth(routed_fleet["admin"]))
    ).json()
    card = next(c for c in cards if c["kind"] == "reroute")

    response = await client.post(
        f"/api/v1/copilot/recommendations/{card['id']}/apply",
        headers=auth(routed_fleet["dispatcher"]),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_an_unreachable_routing_engine_reports_instead_of_guessing(
    client: AsyncClient, db: AsyncSession, routed_fleet
) -> None:
    """A straight-line 'alternative' would be a confidently wrong ETA."""
    set_osrm_client(FakeOsrm(available=False))
    try:
        body = (
            await client.get(
                "/api/v1/reroutes/proposals", headers=auth(routed_fleet["admin"])
            )
        ).json()
        assert len(body) == 1
        assert body[0]["routing_available"] is False
        assert body[0]["added_km"] is None

        cards = (
            await client.post(
                "/api/v1/copilot/run", headers=auth(routed_fleet["admin"])
            )
        ).json()
        card = next(c for c in cards if c["kind"] == "reroute")
        assert card["action_payload"] is None, "there is nothing safe to apply"
    finally:
        set_osrm_client(OsrmClient())


@pytest.mark.asyncio
async def test_the_detour_waypoint_actually_leaves_the_closure(
    db: AsyncSession, routed_fleet, osrm
) -> None:
    hits = await rerouting.detect(db, routed_fleet["org"].id)
    task, route, obstruction = hits[0]
    proposal = await rerouting.propose(
        db, routed_fleet["scope"], task=task, route=route, obstruction=obstruction
    )

    distance = geo.haversine_m(
        proposal.detour_latitude,
        proposal.detour_longitude,
        obstruction.latitude,
        obstruction.longitude,
    )
    assert distance > obstruction.radius_m


@pytest.mark.asyncio
async def test_rerouting_a_finished_task_is_refused(
    client: AsyncClient, db: AsyncSession, routed_fleet, osrm
) -> None:
    cards = (
        await client.post("/api/v1/copilot/run", headers=auth(routed_fleet["admin"]))
    ).json()
    card = next(c for c in cards if c["kind"] == "reroute")

    routed_fleet["task"].status = TaskStatus.COMPLETED
    await db.commit()

    response = await client.post(
        f"/api/v1/copilot/recommendations/{card['id']}/apply",
        headers=auth(routed_fleet["admin"]),
    )
    assert response.status_code == 422
    assert "no longer running" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Audit log viewing
# ---------------------------------------------------------------------------

@pytest.fixture
async def two_tenants_with_history(client: AsyncClient, db: AsyncSession):
    org_a = await make_organization(db, "Echo Transit")
    org_b = await make_organization(db, "Foxtrot Freight")
    await make_user(
        db, email="admin@echo.example.com", role=UserRole.ORG_ADMIN, organization=org_a
    )
    await make_user(
        db,
        email="admin@foxtrot.example.com",
        role=UserRole.ORG_ADMIN,
        organization=org_b,
    )
    await make_user(db, email="root@fleetbeat.example.com", role=UserRole.SUPER_ADMIN)

    db.add_all(
        [
            AuditLog(
                organization_id=org_a.id,
                action="update",
                entity_type="vehicle",
                summary="Echo changed a vehicle",
                actor_email="admin@echo.example.com",
            ),
            AuditLog(
                organization_id=org_b.id,
                action="delete",
                entity_type="vehicle",
                summary="Foxtrot deleted a vehicle",
                actor_email="admin@foxtrot.example.com",
            ),
            AuditLog(
                organization_id=None,
                action="organization_created",
                summary="Platform created Foxtrot Freight",
                actor_email="root@fleetbeat.example.com",
            ),
        ]
    )
    await db.commit()

    return {
        "org_a": org_a,
        "org_b": org_b,
        "admin_a": await login(client, "admin@echo.example.com"),
        "super": await login(client, "root@fleetbeat.example.com"),
    }


@pytest.mark.asyncio
async def test_an_org_admin_sees_only_their_own_audit_trail(
    client: AsyncClient, two_tenants_with_history
) -> None:
    response = await client.get(
        "/api/v1/audit-log", headers=auth(two_tenants_with_history["admin_a"])
    )
    assert response.status_code == 200
    summaries = [row["summary"] for row in response.json()["items"]]

    assert any("Echo changed a vehicle" in s for s in summaries)
    assert not any("Foxtrot" in (s or "") for s in summaries)
    # Platform-level rows carry no organization, and are not theirs to read.
    assert not any("Platform created" in (s or "") for s in summaries)


@pytest.mark.asyncio
async def test_a_dispatcher_cannot_read_the_audit_trail(
    client: AsyncClient, db: AsyncSession, two_tenants_with_history
) -> None:
    await make_user(
        db,
        email="dispatch@echo.example.com",
        role=UserRole.DISPATCHER,
        organization=two_tenants_with_history["org_a"],
    )
    await db.commit()
    token = await login(client, "dispatch@echo.example.com")

    assert (await client.get("/api/v1/audit-log", headers=auth(token))).status_code == 403


@pytest.mark.asyncio
async def test_an_org_admin_cannot_reach_the_platform_wide_trail(
    client: AsyncClient, two_tenants_with_history
) -> None:
    response = await client.get(
        "/api/v1/platform/audit-log",
        headers=auth(two_tenants_with_history["admin_a"]),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_a_super_admin_sees_every_tenant_and_the_platform_rows(
    client: AsyncClient, two_tenants_with_history
) -> None:
    response = await client.get(
        "/api/v1/platform/audit-log", headers=auth(two_tenants_with_history["super"])
    )
    assert response.status_code == 200
    items = response.json()["items"]
    summaries = [row["summary"] for row in items]

    assert any("Echo changed" in (s or "") for s in summaries)
    assert any("Foxtrot deleted" in (s or "") for s in summaries)
    assert any("Platform created" in (s or "") for s in summaries)
    # Rows are labelled with their tenant so the view is readable.
    named = {row["organization_name"] for row in items}
    assert "Echo Transit" in named and "Foxtrot Freight" in named


@pytest.mark.asyncio
async def test_the_platform_trail_can_be_narrowed_to_one_tenant(
    client: AsyncClient, two_tenants_with_history
) -> None:
    response = await client.get(
        f"/api/v1/platform/audit-log?organization_id={two_tenants_with_history['org_b'].id}",
        headers=auth(two_tenants_with_history["super"]),
    )
    summaries = [row["summary"] for row in response.json()["items"]]
    assert summaries == ["Foxtrot deleted a vehicle"]


@pytest.mark.asyncio
async def test_the_audit_log_is_read_only_over_the_api(
    client: AsyncClient, two_tenants_with_history
) -> None:
    """Append-only means no route exists to edit or delete an entry."""
    from app.main import app

    audit_paths = [
        route.path
        for route in app.routes
        if "audit-log" in getattr(route, "path", "")
    ]
    assert audit_paths, "the audit-log routes should exist"
    for route in app.routes:
        if "audit-log" in getattr(route, "path", ""):
            assert set(route.methods) <= {"GET", "HEAD", "OPTIONS"}, route.path


# ---------------------------------------------------------------------------
# Login activity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_activity_is_scoped_through_the_user_table(
    client: AsyncClient, db: AsyncSession, two_tenants_with_history
) -> None:
    """login_attempts has no organization_id, so the join is the isolation."""
    users = {
        user.email: user
        for user in (
            await db.execute(sa.select(__import__("app.models.user", fromlist=["User"]).User))
        ).scalars().all()
    }
    db.add_all(
        [
            LoginAttempt(
                email="admin@echo.example.com",
                user_id=users["admin@echo.example.com"].id,
                successful=True,
                suspicious=True,
                suspicion_reason="New device",
                attempted_at=datetime.now(UTC),
            ),
            LoginAttempt(
                email="admin@foxtrot.example.com",
                user_id=users["admin@foxtrot.example.com"].id,
                successful=False,
                attempted_at=datetime.now(UTC),
            ),
            LoginAttempt(
                email="nobody@nowhere.example.com",
                user_id=None,
                successful=False,
                attempted_at=datetime.now(UTC),
            ),
        ]
    )
    await db.commit()

    body = (
        await client.get(
            "/api/v1/security/login-activity",
            headers=auth(two_tenants_with_history["admin_a"]),
        )
    ).json()
    emails = {row["email"] for row in body["items"]}
    assert emails == {"admin@echo.example.com"}

    # The platform view sees everything, including attempts for no known user.
    platform = (
        await client.get(
            "/api/v1/platform/security/login-activity",
            headers=auth(two_tenants_with_history["super"]),
        )
    ).json()
    assert {row["email"] for row in platform["items"]} >= {
        "admin@echo.example.com",
        "admin@foxtrot.example.com",
        "nobody@nowhere.example.com",
    }


@pytest.mark.asyncio
async def test_the_security_overview_counts_only_this_tenant(
    client: AsyncClient, db: AsyncSession, two_tenants_with_history
) -> None:
    from app.models.user import User

    echo_admin = (
        await db.execute(
            sa.select(User).where(User.email == "admin@echo.example.com")
        )
    ).scalar_one()
    foxtrot_admin = (
        await db.execute(
            sa.select(User).where(User.email == "admin@foxtrot.example.com")
        )
    ).scalar_one()

    db.add_all(
        [
            LoginAttempt(
                email=echo_admin.email,
                user_id=echo_admin.id,
                successful=True,
                suspicious=True,
                attempted_at=datetime.now(UTC),
            ),
            LoginAttempt(
                email=foxtrot_admin.email,
                user_id=foxtrot_admin.id,
                successful=True,
                suspicious=True,
                attempted_at=datetime.now(UTC),
            ),
        ]
    )
    await db.commit()

    body = (
        await client.get(
            "/api/v1/security/overview",
            headers=auth(two_tenants_with_history["admin_a"]),
        )
    ).json()
    assert body["suspicious_logins_7d"] == 1


@pytest.mark.asyncio
async def test_road_closures_are_tenant_scoped(
    client: AsyncClient, db: AsyncSession, two_tenants_with_history
) -> None:
    closure = RoadClosure(
        organization_id=two_tenants_with_history["org_b"].id,
        label="Foxtrot's closure",
        latitude=52.0,
        longitude=4.0,
        radius_m=300.0,
    )
    db.add(closure)
    await db.commit()

    listed = (
        await client.get(
            "/api/v1/road-closures", headers=auth(two_tenants_with_history["admin_a"])
        )
    ).json()
    assert listed == []

    direct = await client.patch(
        f"/api/v1/road-closures/{closure.id}",
        headers=auth(two_tenants_with_history["admin_a"]),
        json={"is_active": False},
    )
    assert direct.status_code == 404
    await db.refresh(closure)
    assert closure.is_active is True


@pytest.mark.asyncio
async def test_a_closure_is_created_scoped_to_the_callers_own_tenant(
    client: AsyncClient, db: AsyncSession, two_tenants_with_history
) -> None:
    """A client-sent organization_id must be ignored, not honoured."""
    response = await client.post(
        "/api/v1/road-closures",
        headers=auth(two_tenants_with_history["admin_a"]),
        json={
            "label": "Ring road works",
            "latitude": 52.36,
            "longitude": 4.88,
            "radius_m": 300,
            "organization_id": str(two_tenants_with_history["org_b"].id),
        },
    )
    assert response.status_code == 201

    closure = (
        await db.execute(
            sa.select(RoadClosure).where(RoadClosure.label == "Ring road works")
        )
    ).scalar_one()
    assert closure.organization_id == two_tenants_with_history["org_a"].id


def test_the_polyline_decoder_matches_the_reference_implementation() -> None:
    """The canonical Google/OSRM example, so detection reads real geometry."""
    assert geo.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == [
        (38.5, -120.2),
        (40.7, -120.95),
        (43.252, -126.453),
    ]
    assert geo.decode_polyline("") == []
    assert geo.decode_polyline(encode(CLEAR_PATH)) == pytest.approx(CLEAR_PATH)
