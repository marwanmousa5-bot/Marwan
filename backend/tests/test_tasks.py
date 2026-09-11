"""Task Manager and the driver app (Section 4f, Section 4 item 14).

The four-state lifecycle is mandatory, so it is tested as a contract: the
allowed moves, the refused ones, and the rule that a driver can only ever act
on their own work.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import Driver
from app.models.enums import TaskStatus, UserRole
from app.models.incident import Incident
from app.models.tracking import Trip
from app.models.vehicle import Vehicle
from app.services.notifications import (
    RecordingNotificationService,
    get_push_service,
    set_push_service,
)
from tests.conftest import auth, login, make_organization, make_user

DESTINATION = {"destination_latitude": 52.3105, "destination_longitude": 4.7683}


@pytest.fixture
async def dispatch(client: AsyncClient, db: AsyncSession):
    org = await make_organization(db, "Acme Logistics")
    await make_user(
        db, email="admin@acme.example.com", role=UserRole.ORG_ADMIN, organization=org
    )
    driver_user = await make_user(
        db, email="dee@acme.example.com", role=UserRole.DRIVER, organization=org
    )
    other_user = await make_user(
        db, email="sam@acme.example.com", role=UserRole.DRIVER, organization=org
    )

    vehicle = Vehicle(
        organization_id=org.id,
        name="Van 01",
        license_plate="ACM-001",
        last_latitude=52.3676,
        last_longitude=4.9041,
    )
    db.add(vehicle)
    await db.flush()

    driver = Driver(
        organization_id=org.id,
        user_id=driver_user.id,
        full_name="Dee Driver",
        assigned_vehicle_id=vehicle.id,
    )
    other = Driver(
        organization_id=org.id, user_id=other_user.id, full_name="Sam Roads"
    )
    db.add_all([driver, other])
    await db.commit()

    return {
        "org": org,
        "vehicle": vehicle,
        "driver": driver,
        "other": other,
        "admin": await login(client, "admin@acme.example.com"),
        "driver_token": await login(client, "dee@acme.example.com"),
        "other_token": await login(client, "sam@acme.example.com"),
    }


async def _create_task(client: AsyncClient, dispatch, **overrides) -> dict:
    body = {
        "title": "Deliver pallet 42",
        "task_type": "delivery",
        "driver_id": str(dispatch["driver"].id),
        "destination_label": "Schiphol hub",
        **DESTINATION,
        **overrides,
    }
    response = await client.post(
        "/api/v1/tasks", headers=auth(dispatch["admin"]), json=body
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_created_task_starts_assigned_and_follows_the_drivers_vehicle(
    client: AsyncClient, dispatch
) -> None:
    task = await _create_task(client, dispatch)
    assert task["status"] == TaskStatus.ASSIGNED.value
    assert task["driver_name"] == "Dee Driver"
    # The task follows the driver's currently assigned vehicle.
    assert task["vehicle_id"] == str(dispatch["vehicle"].id)
    assert task["vehicle_name"] == "Van 01"


@pytest.mark.asyncio
async def test_assignment_pushes_a_notification_to_the_driver(
    client: AsyncClient, dispatch
) -> None:
    recorder = RecordingNotificationService()
    previous = get_push_service()
    set_push_service(recorder)
    try:
        await _create_task(client, dispatch)
    finally:
        set_push_service(previous)

    assert len(recorder.sent) == 1
    assert recorder.sent[0].channel == "push"
    assert "assigned" in recorder.sent[0].subject


@pytest.mark.asyncio
async def test_full_lifecycle_accept_start_complete(
    client: AsyncClient, dispatch, db: AsyncSession
) -> None:
    task = await _create_task(client, dispatch)
    token = dispatch["driver_token"]

    accepted = await client.post(
        f"/api/v1/driver/tasks/{task['id']}/accept", headers=auth(token)
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["accepted_at"] is not None

    started = await client.post(
        f"/api/v1/driver/tasks/{task['id']}/start", headers=auth(token)
    )
    assert started.json()["status"] == "en_route"
    # Starting binds the assignment to a recorded trip (Section 4f).
    assert started.json()["trip_id"] is not None

    completed = await client.post(
        f"/api/v1/driver/tasks/{task['id']}/complete",
        headers=auth(token),
        json={"completion_note": "Left at reception", "completion_photo_url": "/p/1.jpg"},
    )
    assert completed.json()["status"] == "completed"
    assert completed.json()["completion_note"] == "Left at reception"

    trip = (await db.execute(sa.select(Trip))).scalar_one()
    assert trip.task_id == uuid.UUID(task["id"])


@pytest.mark.asyncio
async def test_illegal_transitions_are_refused(
    client: AsyncClient, dispatch
) -> None:
    task = await _create_task(client, dispatch)
    token = dispatch["driver_token"]

    # Cannot start a task that has not been accepted.
    skipped = await client.post(
        f"/api/v1/driver/tasks/{task['id']}/start", headers=auth(token)
    )
    assert skipped.status_code == 422

    await client.post(f"/api/v1/driver/tasks/{task['id']}/accept", headers=auth(token))
    # Cannot complete before going en route.
    early = await client.post(
        f"/api/v1/driver/tasks/{task['id']}/complete", headers=auth(token), json={}
    )
    assert early.status_code == 422

    await client.post(f"/api/v1/driver/tasks/{task['id']}/start", headers=auth(token))
    await client.post(
        f"/api/v1/driver/tasks/{task['id']}/complete", headers=auth(token), json={}
    )
    # A completed task is terminal.
    reopened = await client.post(
        f"/api/v1/driver/tasks/{task['id']}/accept", headers=auth(token)
    )
    assert reopened.status_code == 422


@pytest.mark.asyncio
async def test_a_driver_cannot_act_on_another_drivers_task(
    client: AsyncClient, dispatch
) -> None:
    task = await _create_task(client, dispatch)

    stolen = await client.post(
        f"/api/v1/driver/tasks/{task['id']}/accept",
        headers=auth(dispatch["other_token"]),
    )
    # 404, not 403: another driver's workload is not theirs to know about.
    assert stolen.status_code == 404

    listed = await client.get(
        "/api/v1/driver/tasks", headers=auth(dispatch["other_token"])
    )
    assert listed.json() == []


@pytest.mark.asyncio
async def test_reassignment_is_allowed_before_acceptance_only(
    client: AsyncClient, dispatch
) -> None:
    task = await _create_task(client, dispatch)

    moved = await client.post(
        f"/api/v1/tasks/{task['id']}/reassign",
        headers=auth(dispatch["admin"]),
        json={"driver_id": str(dispatch["other"].id)},
    )
    assert moved.status_code == 200
    assert moved.json()["driver_name"] == "Sam Roads"
    # Sam has no vehicle assigned, so the task carries none either.
    assert moved.json()["vehicle_id"] is None

    await client.post(
        f"/api/v1/driver/tasks/{task['id']}/accept",
        headers=auth(dispatch["other_token"]),
    )
    late = await client.post(
        f"/api/v1/tasks/{task['id']}/reassign",
        headers=auth(dispatch["admin"]),
        json={"driver_id": str(dispatch["driver"].id)},
    )
    assert late.status_code == 422
    assert "accepted" in late.json()["detail"]


@pytest.mark.asyncio
async def test_cancellation_is_reachable_from_any_open_state(
    client: AsyncClient, dispatch
) -> None:
    first = await _create_task(client, dispatch)
    cancelled = await client.post(
        f"/api/v1/tasks/{first['id']}/cancel",
        headers=auth(dispatch["admin"]),
        json={"reason": "Customer postponed"},
    )
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancellation_reason"] == "Customer postponed"

    second = await _create_task(client, dispatch, title="Second job")
    await client.post(
        f"/api/v1/driver/tasks/{second['id']}/accept",
        headers=auth(dispatch["driver_token"]),
    )
    await client.post(
        f"/api/v1/driver/tasks/{second['id']}/start",
        headers=auth(dispatch["driver_token"]),
    )
    late_cancel = await client.post(
        f"/api/v1/tasks/{second['id']}/cancel",
        headers=auth(dispatch["admin"]),
        json={"reason": "Site closed"},
    )
    assert late_cancel.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_driver_home_reports_todays_work(
    client: AsyncClient, dispatch
) -> None:
    await _create_task(client, dispatch)
    await _create_task(client, dispatch, title="Second job")

    home = await client.get(
        "/api/v1/driver/home", headers=auth(dispatch["driver_token"])
    )
    assert home.status_code == 200, home.text
    body = home.json()
    assert body["driver_name"] == "Dee Driver"
    assert body["vehicle_plate"] == "ACM-001"
    assert len(body["tasks"]) == 2
    assert body["inspection_due"] is True
    # Off by default (Section 4g) unless the Org Admin opts in.
    assert body["leaderboard_visible"] is False


@pytest.mark.asyncio
async def test_leaderboard_visibility_follows_the_org_setting(
    client: AsyncClient, dispatch
) -> None:
    await client.patch(
        "/api/v1/organization/settings",
        headers=auth(dispatch["admin"]),
        json={"show_leaderboard_to_drivers": True},
    )
    home = await client.get(
        "/api/v1/driver/home", headers=auth(dispatch["driver_token"])
    )
    assert home.json()["leaderboard_visible"] is True


@pytest.mark.asyncio
async def test_passing_inspection_clears_the_prompt(
    client: AsyncClient, dispatch, db: AsyncSession
) -> None:
    submitted = await client.post(
        "/api/v1/driver/inspections",
        headers=auth(dispatch["driver_token"]),
        json={
            "vehicle_id": str(dispatch["vehicle"].id),
            "items": [
                {"code": "tyres", "label": "Tyres", "ok": True},
                {"code": "lights", "label": "Lights", "ok": True},
            ],
            "odometer_km": 12345,
        },
    )
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["passed"] is True

    home = await client.get(
        "/api/v1/driver/home", headers=auth(dispatch["driver_token"])
    )
    assert home.json()["inspection_due"] is False

    assert (
        await db.execute(sa.select(sa.func.count()).select_from(Incident))
    ).scalar_one() == 0


@pytest.mark.asyncio
async def test_failed_inspection_raises_an_incident(
    client: AsyncClient, dispatch, db: AsyncSession
) -> None:
    """A failed check must reach someone, not sit in a form nobody opens."""
    response = await client.post(
        "/api/v1/driver/inspections",
        headers=auth(dispatch["driver_token"]),
        json={
            "vehicle_id": str(dispatch["vehicle"].id),
            "items": [
                {"code": "tyres", "label": "Tyres", "ok": False, "note": "Near-side worn"},
                {"code": "lights", "label": "Lights", "ok": True},
            ],
        },
    )
    assert response.status_code == 201
    assert response.json()["passed"] is False

    incident = (await db.execute(sa.select(Incident))).scalar_one()
    assert "Tyres" in incident.title
    assert incident.vehicle_id == dispatch["vehicle"].id
    assert incident.driver_id == dispatch["driver"].id


@pytest.mark.asyncio
async def test_driver_incident_is_always_attributed_to_the_caller(
    client: AsyncClient, dispatch, db: AsyncSession
) -> None:
    """A driver cannot file a report in someone else's name."""
    response = await client.post(
        "/api/v1/driver/incidents",
        headers=auth(dispatch["driver_token"]),
        json={
            "title": "Kerbed the near-side wheel",
            "severity": "minor",
            "driver_id": str(dispatch["other"].id),
            "latitude": 52.37,
            "longitude": 4.9,
            "photo_urls": ["/uploads/1.jpg"],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["driver_id"] == str(dispatch["driver"].id)
    assert response.json()["photo_urls"] == ["/uploads/1.jpg"]
    # It defaults to the driver's own vehicle.
    assert response.json()["vehicle_id"] == str(dispatch["vehicle"].id)


@pytest.mark.asyncio
async def test_dispatcher_sees_driver_reported_incidents(
    client: AsyncClient, dispatch
) -> None:
    await client.post(
        "/api/v1/driver/incidents",
        headers=auth(dispatch["driver_token"]),
        json={"title": "Windscreen chip", "severity": "minor"},
    )
    listed = await client.get("/api/v1/incidents", headers=auth(dispatch["admin"]))
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["title"] == "Windscreen chip"


@pytest.mark.asyncio
async def test_tasks_are_tenant_scoped(
    client: AsyncClient, dispatch, db: AsyncSession
) -> None:
    task = await _create_task(client, dispatch)

    rival = await make_organization(db, "Rival Freight")
    await make_user(
        db, email="rex@rival.example.com", role=UserRole.ORG_ADMIN, organization=rival
    )
    await db.commit()
    token = await login(client, "rex@rival.example.com")

    assert (
        await client.get(f"/api/v1/tasks/{task['id']}", headers=auth(token))
    ).status_code == 404
    assert (await client.get("/api/v1/tasks", headers=auth(token))).json()["total"] == 0


@pytest.mark.asyncio
async def test_dashboard_roles_cannot_use_the_driver_api(
    client: AsyncClient, dispatch
) -> None:
    assert (
        await client.get("/api/v1/driver/home", headers=auth(dispatch["admin"]))
    ).status_code == 403


@pytest.mark.asyncio
async def test_driver_without_a_profile_gets_a_clear_message(
    client: AsyncClient, db: AsyncSession
) -> None:
    org = await make_organization(db, "Acme Logistics")
    await make_user(
        db, email="orphan@acme.example.com", role=UserRole.DRIVER, organization=org
    )
    await db.commit()
    token = await login(client, "orphan@acme.example.com")

    response = await client.get("/api/v1/driver/home", headers=auth(token))
    assert response.status_code == 403
    assert "driver profile" in response.json()["detail"]
