"""AI layer: assistant, copilots, reporting and export (Sections 4e, 5).

The most important property here is the one Section 9 states without
exception: no agentic feature changes data without an explicit confirmation
step. That is tested from both directions - that the propose call changes
nothing, and that the apply call refuses without a valid confirmation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import copilot, reports
from app.ai.client import ClaudeClient, LLMResponse, get_claude_client, set_claude_client
from app.core.tenancy import TenantScope
from app.models.ai import Recommendation
from app.models.driver import Driver
from app.models.enums import (
    RecommendationStatus,
    TaskStatus,
    UserRole,
    VehicleStatus,
    WorkOrderStatus,
)
from app.models.maintenance import WorkOrder
from app.models.task import Task
from app.models.tracking import Trip
from app.models.vehicle import Vehicle
from app.services import exports
from tests.conftest import auth, login, make_organization, make_user


class FakeClaude(ClaudeClient):
    """A stand-in that returns scripted responses without any network call."""

    def __init__(self, *, intent: dict | None = None, text: str = "Scripted answer."):
        super().__init__(api_key="test-key", model="claude-opus-5")
        self.intent = intent
        self.text = text
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kwargs: Any) -> LLMResponse:  # type: ignore[override]
        self.calls.append(kwargs)
        if kwargs.get("json_schema") is not None:
            return LLMResponse(text="", model="claude-opus-5", data=self.intent)
        return LLMResponse(text=self.text, model="claude-opus-5")


@pytest.fixture
def offline_claude():
    """No API key: every feature must still work, from rules alone."""
    previous = get_claude_client()
    set_claude_client(ClaudeClient(api_key=None))
    yield
    set_claude_client(previous)


@pytest.fixture
def scripted_claude():
    previous = get_claude_client()
    created: list[FakeClaude] = []

    def install(**kwargs: Any) -> FakeClaude:
        fake = FakeClaude(**kwargs)
        set_claude_client(fake)
        created.append(fake)
        return fake

    yield install
    set_claude_client(previous)


@pytest.fixture
async def fleet(client: AsyncClient, db: AsyncSession):
    org = await make_organization(db, "Acme Logistics")
    await make_user(
        db, email="admin@acme.example.com", role=UserRole.ORG_ADMIN, organization=org
    )
    await make_user(
        db, email="dispatch@acme.example.com", role=UserRole.DISPATCHER, organization=org
    )

    working = Vehicle(
        organization_id=org.id, name="Van 01", license_plate="ACM-001", odometer_km=50_000
    )
    in_shop = Vehicle(
        organization_id=org.id,
        name="Truck 03",
        license_plate="ACM-003",
        status=VehicleStatus.IN_MAINTENANCE,
    )
    db.add_all([working, in_shop])
    await db.flush()

    driver = Driver(
        organization_id=org.id, full_name="Dee Driver", assigned_vehicle_id=in_shop.id
    )
    db.add(driver)
    await db.flush()

    # An open task on the vehicle that is in the workshop.
    db.add(
        Task(
            organization_id=org.id,
            title="Deliver pallet 42",
            driver_id=driver.id,
            vehicle_id=in_shop.id,
            destination_latitude=52.31,
            destination_longitude=4.76,
            status=TaskStatus.ASSIGNED,
        )
    )
    await db.commit()

    return {
        "org": org,
        "scope": TenantScope(org.id),
        "vehicle": working,
        "in_shop": in_shop,
        "driver": driver,
        "admin": await login(client, "admin@acme.example.com"),
        "dispatcher": await login(client, "dispatch@acme.example.com"),
    }


# ---------------------------------------------------------------------------
# The confirmation gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_asking_for_an_action_changes_nothing(
    client: AsyncClient, db: AsyncSession, fleet, scripted_claude
) -> None:
    """Section 9: proposing is not applying."""
    scripted_claude(
        intent={
            "capability": "cancel_tasks_for_vehicles_in_maintenance",
            "parameters": {},
            "reasoning": "The user asked to cancel tasks for vehicles in maintenance.",
        }
    )

    response = await client.post(
        "/api/v1/assistant/ask",
        headers=auth(fleet["admin"]),
        json={"question": "Cancel tomorrow's tasks for vehicles with maintenance due"},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["kind"] == "action"
    assert body["pending_action"] is not None
    assert body["data"]["affected_count"] == 1
    assert "confirm" in body["answer"].lower()

    # Nothing has changed.
    task = (await db.execute(sa.select(Task))).scalar_one()
    await db.refresh(task)
    assert task.status == TaskStatus.ASSIGNED


@pytest.mark.asyncio
async def test_confirming_applies_the_action_and_audits_it(
    client: AsyncClient, db: AsyncSession, fleet, scripted_claude
) -> None:
    scripted_claude(
        intent={
            "capability": "cancel_tasks_for_vehicles_in_maintenance",
            "parameters": {},
            "reasoning": "-",
        }
    )
    proposal = (
        await client.post(
            "/api/v1/assistant/ask",
            headers=auth(fleet["admin"]),
            json={"question": "Cancel tasks for vehicles in maintenance"},
        )
    ).json()

    applied = await client.post(
        "/api/v1/assistant/confirm",
        headers=auth(fleet["admin"]),
        json={"pending_action": proposal["pending_action"]},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied_count"] == 1

    task = (await db.execute(sa.select(Task))).scalar_one()
    await db.refresh(task)
    assert task.status == TaskStatus.CANCELLED

    from app.models.audit import AuditLog

    actions = {
        row[0] for row in (await db.execute(sa.select(AuditLog.action))).all()
    }
    assert "ai_action_confirmed" in actions


@pytest.mark.asyncio
async def test_a_different_user_cannot_confirm_someone_elses_proposal(
    client: AsyncClient, fleet, scripted_claude, db: AsyncSession
) -> None:
    """An approval is for the person who was shown the preview."""
    scripted_claude(
        intent={
            "capability": "cancel_tasks_for_vehicles_in_maintenance",
            "parameters": {},
            "reasoning": "-",
        }
    )
    proposal = (
        await client.post(
            "/api/v1/assistant/ask",
            headers=auth(fleet["dispatcher"]),
            json={"question": "Cancel tasks for vehicles in maintenance"},
        )
    ).json()

    hijacked = await client.post(
        "/api/v1/assistant/confirm",
        headers=auth(fleet["admin"]),
        json={"pending_action": proposal["pending_action"]},
    )
    assert hijacked.status_code == 403

    task = (await db.execute(sa.select(Task))).scalar_one()
    assert task.status == TaskStatus.ASSIGNED


@pytest.mark.asyncio
async def test_an_expired_proposal_is_refused(
    client: AsyncClient, fleet, scripted_claude
) -> None:
    scripted_claude(
        intent={
            "capability": "cancel_tasks_for_vehicles_in_maintenance",
            "parameters": {},
            "reasoning": "-",
        }
    )
    proposal = (
        await client.post(
            "/api/v1/assistant/ask",
            headers=auth(fleet["admin"]),
            json={"question": "Cancel tasks for vehicles in maintenance"},
        )
    ).json()

    stale = dict(proposal["pending_action"])
    stale["expires_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    response = await client.post(
        "/api/v1/assistant/confirm",
        headers=auth(fleet["admin"]),
        json={"pending_action": stale},
    )
    assert response.status_code == 422
    assert "expired" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_a_forged_action_is_refused(client: AsyncClient, fleet) -> None:
    """The confirm endpoint only applies capabilities it knows."""
    response = await client.post(
        "/api/v1/assistant/confirm",
        headers=auth(fleet["admin"]),
        json={
            "pending_action": {
                "capability": "delete_everything",
                "parameters": {},
                "requested_by": "whoever",
            }
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_dispatchers_cannot_apply_actions(
    client: AsyncClient, fleet, scripted_claude
) -> None:
    scripted_claude(
        intent={
            "capability": "cancel_tasks_for_vehicles_in_maintenance",
            "parameters": {},
            "reasoning": "-",
        }
    )
    proposal = (
        await client.post(
            "/api/v1/assistant/ask",
            headers=auth(fleet["dispatcher"]),
            json={"question": "Cancel tasks for vehicles in maintenance"},
        )
    ).json()

    response = await client.post(
        "/api/v1/assistant/confirm",
        headers=auth(fleet["dispatcher"]),
        json={"pending_action": proposal["pending_action"]},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_query_answers_from_real_figures(
    client: AsyncClient, db: AsyncSession, fleet, scripted_claude
) -> None:
    fake = scripted_claude(
        intent={
            "capability": "most_expensive_vehicle",
            "parameters": {"days": 30},
            "reasoning": "-",
        },
        text="Van 01 cost the most this month.",
    )

    await client.post(
        "/api/v1/fuel/logs",
        headers=auth(fleet["admin"]),
        json={
            "vehicle_id": str(fleet["vehicle"].id),
            "fuel_type": "diesel",
            "quantity": 60,
            "total_cost": 250,
            "filled_at": datetime.now(UTC).isoformat(),
        },
    )

    response = await client.post(
        "/api/v1/assistant/ask",
        headers=auth(fleet["admin"]),
        json={"question": "Which vehicle cost the most this month?"},
    )
    body = response.json()

    assert body["kind"] == "query"
    assert body["data"]["answer_vehicle"]["name"] == "Van 01"
    assert body["data"]["answer_vehicle"]["total_cost"] == 250
    # The figures handed to the model came from our own query, not from it.
    narration = fake.calls[-1]
    assert "250" in narration["prompt"]


@pytest.mark.asyncio
async def test_the_assistant_works_with_no_api_key(
    client: AsyncClient, db: AsyncSession, fleet, offline_claude
) -> None:
    """No key must mean plainer prose, not a broken feature."""
    await client.post(
        "/api/v1/fuel/logs",
        headers=auth(fleet["admin"]),
        json={
            "vehicle_id": str(fleet["vehicle"].id),
            "fuel_type": "diesel",
            "quantity": 60,
            "total_cost": 250,
            "filled_at": datetime.now(UTC).isoformat(),
        },
    )

    response = await client.post(
        "/api/v1/assistant/ask",
        headers=auth(fleet["admin"]),
        json={"question": "Which vehicle cost the most?"},
    )
    body = response.json()

    assert body["capability"] == "most_expensive_vehicle"
    assert body["offline"] is True
    # The answer still carries the real number.
    assert "Van 01" in body["answer"]
    assert "250" in body["answer"]


@pytest.mark.asyncio
async def test_an_unmatched_question_is_declined_not_guessed(
    client: AsyncClient, fleet, offline_claude
) -> None:
    response = await client.post(
        "/api/v1/assistant/ask",
        headers=auth(fleet["admin"]),
        json={"question": "What is the airspeed velocity of an unladen swallow?"},
    )
    assert response.json()["capability"] == "unsupported"
    assert response.json()["kind"] == "none"


@pytest.mark.asyncio
async def test_assistant_queries_are_tenant_scoped(
    client: AsyncClient, db: AsyncSession, fleet, offline_claude
) -> None:
    rival = await make_organization(db, "Rival Freight")
    await make_user(
        db, email="rex@rival.example.com", role=UserRole.ORG_ADMIN, organization=rival
    )
    await db.commit()

    token = await login(client, "rex@rival.example.com")
    response = await client.post(
        "/api/v1/assistant/ask",
        headers=auth(token),
        json={"question": "Which vehicle cost the most?"},
    )
    # Acme's vehicles must not appear in Rival's answer.
    assert response.json()["data"]["vehicles"] == []


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_copilot_detects_a_late_task_from_the_plan_not_the_model(
    db: AsyncSession, fleet, offline_claude
) -> None:
    """The facts are ours; the model only phrases them."""
    now = datetime.now(UTC)
    task = (await db.execute(sa.select(Task))).scalar_one()
    task.due_at = now + timedelta(minutes=20)
    task.eta = now + timedelta(minutes=75)
    await db.commit()

    signals = await copilot.gather_signals(db, fleet["org"].id, now=now)
    late = [s for s in signals if s.kind == "late_task"]
    assert len(late) == 1
    assert late[0].impact_minutes == pytest.approx(55, abs=2)


@pytest.mark.asyncio
async def test_copilot_creates_recommendations_and_dedupes_them(
    client: AsyncClient, db: AsyncSession, fleet, offline_claude
) -> None:
    now = datetime.now(UTC)
    task = (await db.execute(sa.select(Task))).scalar_one()
    task.due_at = now + timedelta(minutes=10)
    task.eta = now + timedelta(minutes=60)
    await db.commit()

    first = await client.post("/api/v1/copilot/run", headers=auth(fleet["admin"]))
    assert first.status_code == 200
    assert len(first.json()) >= 1

    # Running again in the same window must not pile up duplicates.
    second = await client.post("/api/v1/copilot/run", headers=auth(fleet["admin"]))
    assert len(second.json()) == len(first.json())


@pytest.mark.asyncio
async def test_an_informational_recommendation_has_nothing_to_apply(
    client: AsyncClient, db: AsyncSession, fleet, offline_claude
) -> None:
    recommendation = Recommendation(
        organization_id=fleet["org"].id,
        kind="copilot",
        status=RecommendationStatus.PENDING,
        title="Three alerts on Truck 03",
        summary="Several unresolved alerts on one vehicle.",
        action_payload=None,
    )
    db.add(recommendation)
    await db.commit()

    response = await client.post(
        f"/api/v1/copilot/recommendations/{recommendation.id}/apply",
        headers=auth(fleet["admin"]),
    )
    assert response.status_code == 422
    assert "informational" in response.json()["detail"]


@pytest.mark.asyncio
async def test_dismissing_stops_a_recommendation_resurfacing(
    client: AsyncClient, db: AsyncSession, fleet, offline_claude
) -> None:
    recommendation = Recommendation(
        organization_id=fleet["org"].id,
        kind="copilot",
        status=RecommendationStatus.PENDING,
        title="Something",
        summary="Something happened.",
        dedupe_key="fixed-key",
    )
    db.add(recommendation)
    await db.commit()

    await client.post(
        f"/api/v1/copilot/recommendations/{recommendation.id}/dismiss",
        headers=auth(fleet["admin"]),
    )
    listed = await client.get(
        "/api/v1/copilot/recommendations", headers=auth(fleet["admin"])
    )
    assert listed.json() == []


# ---------------------------------------------------------------------------
# Maintenance Copilot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_maintenance_copilot_proposes_but_does_not_book_by_default(
    client: AsyncClient, db: AsyncSession, fleet, offline_claude
) -> None:
    """Auto-booking is opt-in: a work order costs real money (Section 5.2)."""
    now = datetime.now(UTC)
    for day in range(10):
        db.add(
            Trip(
                organization_id=fleet["org"].id,
                vehicle_id=fleet["vehicle"].id,
                status="completed",
                started_at=now - timedelta(days=day, hours=2),
                distance_km=300.0,
            )
        )
    await db.commit()

    await client.post(
        "/api/v1/maintenance/schedules",
        headers=auth(fleet["admin"]),
        json={
            "vehicle_id": str(fleet["vehicle"].id),
            "name": "Oil change",
            "interval_type": "mileage",
            "interval_km": 10_000,
            "last_service_odometer_km": 42_000,
        },
    )

    response = await client.post(
        "/api/v1/copilot/maintenance-windows", headers=auth(fleet["admin"])
    )
    assert response.status_code == 200, response.text
    proposals = response.json()
    assert len(proposals) == 1
    assert proposals[0]["auto_booked"] is False
    assert proposals[0]["work_order_id"] is None

    # Nothing was created.
    assert (
        await db.execute(sa.select(sa.func.count()).select_from(WorkOrder))
    ).scalar_one() == 0

    # It is offered as a one-click approval instead.
    recommendations = await client.get(
        "/api/v1/copilot/recommendations", headers=auth(fleet["admin"])
    )
    windows = [
        r for r in recommendations.json() if r["kind"] == "maintenance_window"
    ]
    assert len(windows) == 1
    assert windows[0]["action_payload"]["op"] == "create_work_order"


@pytest.mark.asyncio
async def test_auto_book_creates_the_work_order_once_enabled(
    client: AsyncClient, db: AsyncSession, fleet, offline_claude
) -> None:
    now = datetime.now(UTC)
    for day in range(10):
        db.add(
            Trip(
                organization_id=fleet["org"].id,
                vehicle_id=fleet["vehicle"].id,
                status="completed",
                started_at=now - timedelta(days=day, hours=2),
                distance_km=300.0,
            )
        )
    await db.commit()

    await client.patch(
        "/api/v1/organization/settings",
        headers=auth(fleet["admin"]),
        json={"maintenance_auto_book_enabled": True},
    )
    await client.post(
        "/api/v1/maintenance/schedules",
        headers=auth(fleet["admin"]),
        json={
            "vehicle_id": str(fleet["vehicle"].id),
            "name": "Oil change",
            "interval_type": "mileage",
            "interval_km": 10_000,
            "last_service_odometer_km": 42_000,
        },
    )

    proposals = (
        await client.post(
            "/api/v1/copilot/maintenance-windows", headers=auth(fleet["admin"])
        )
    ).json()
    assert proposals[0]["auto_booked"] is True

    work_order = (await db.execute(sa.select(WorkOrder))).scalar_one()
    assert work_order.created_by_copilot is True
    assert work_order.copilot_rationale
    assert work_order.status == WorkOrderStatus.OPEN


@pytest.mark.asyncio
async def test_applying_a_window_recommendation_opens_the_work_order(
    client: AsyncClient, db: AsyncSession, fleet, offline_claude
) -> None:
    schedule = (
        await client.post(
            "/api/v1/maintenance/schedules",
            headers=auth(fleet["admin"]),
            json={
                "vehicle_id": str(fleet["vehicle"].id),
                "name": "Brake check",
                "interval_type": "time",
                "interval_days": 180,
            },
        )
    ).json()

    recommendation = Recommendation(
        organization_id=fleet["org"].id,
        kind="maintenance_window",
        status=RecommendationStatus.PENDING,
        title="Book Brake check",
        summary="Quietest day.",
        action_payload={
            "op": "create_work_order",
            "vehicle_id": str(fleet["vehicle"].id),
            "schedule_id": schedule["id"],
            "scheduled_for": (datetime.now(UTC).date() + timedelta(days=4)).isoformat(),
            "title": "Brake check",
        },
    )
    db.add(recommendation)
    await db.commit()

    applied = await client.post(
        f"/api/v1/copilot/recommendations/{recommendation.id}/apply",
        headers=auth(fleet["admin"]),
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"

    work_order = (await db.execute(sa.select(WorkOrder))).scalar_one()
    assert work_order.title == "Brake check"
    assert work_order.scheduled_for is not None


# ---------------------------------------------------------------------------
# Reports and export
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_report_generates_without_a_model(
    client: AsyncClient, db: AsyncSession, fleet, offline_claude
) -> None:
    now = datetime.now(UTC)
    db.add(
        Trip(
            organization_id=fleet["org"].id,
            vehicle_id=fleet["vehicle"].id,
            status="completed",
            started_at=now - timedelta(days=2),
            distance_km=420.0,
            duration_seconds=7200,
        )
    )
    await db.commit()

    response = await client.post(
        "/api/v1/reports/summaries?period_type=weekly", headers=auth(fleet["admin"])
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["generated_by"] == "rule_based"
    assert "420" in body["summary_text"]
    assert body["metrics"]["distance_km"] == 420.0


@pytest.mark.asyncio
async def test_cost_export_produces_csv_and_pdf(
    client: AsyncClient, fleet
) -> None:
    await client.post(
        "/api/v1/fuel/logs",
        headers=auth(fleet["admin"]),
        json={
            "vehicle_id": str(fleet["vehicle"].id),
            "fuel_type": "diesel",
            "quantity": 60,
            "total_cost": 102,
            "filled_at": datetime.now(UTC).isoformat(),
        },
    )

    csv_response = await client.get(
        "/api/v1/reports/costs.csv", headers=auth(fleet["admin"])
    )
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "Van 01" in csv_response.text
    assert "102.00" in csv_response.text

    pdf_response = await client.get(
        "/api/v1/reports/costs.pdf", headers=auth(fleet["admin"])
    )
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"] == "application/pdf"
    assert pdf_response.content.startswith(b"%PDF-")


def test_pdf_output_is_a_parsable_document() -> None:
    """The writer is hand-rolled, so prove a real parser accepts it."""
    pytest.importorskip("pypdf")
    import io

    from pypdf import PdfReader

    pdf = exports.to_pdf(
        title="Fleet cost report",
        subtitle="1-30 September",
        headers=["Vehicle", "Total"],
        rows=[[f"Van {index:02d}", f"{index * 10}.00"] for index in range(1, 60)],
    )
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 2, "long tables must paginate"
    text = reader.pages[0].extract_text()
    assert "Fleet cost report" in text
    assert "Van 01" in text


def test_csv_escapes_and_blanks_correctly() -> None:
    output = exports.to_csv(
        ["Vehicle", "Note"], [["Van, 01", None], ["Truck 03", 'He said "go"']]
    )
    lines = output.strip().splitlines()
    assert lines[0] == "Vehicle,Note"
    assert lines[1] == '"Van, 01",'
    assert '"He said ""go"""' in lines[2]


@pytest.mark.asyncio
async def test_offline_routing_can_still_reach_the_action_and_still_gates_it(
    client: AsyncClient, db: AsyncSession, fleet, offline_claude
) -> None:
    """No API key must not put the one mutating capability out of reach.

    It must also not loosen the gate: the offline route produces a proposal
    exactly like the model route does, and writes nothing (Section 9).
    """
    vehicle = fleet["vehicle"]
    vehicle.status = VehicleStatus.IN_MAINTENANCE
    task = (await db.execute(sa.select(Task))).scalar_one()
    task.vehicle_id = vehicle.id
    task.status = TaskStatus.ASSIGNED
    await db.commit()

    response = await client.post(
        "/api/v1/assistant/ask",
        headers=auth(fleet["admin"]),
        json={"question": "cancel tasks for vehicles in maintenance"},
    )
    body = response.json()
    assert body["capability"] == "cancel_tasks_for_vehicles_in_maintenance"
    assert body["kind"] == "action"
    assert body["pending_action"] is not None

    # Nothing has been written by asking.
    await db.refresh(task)
    assert task.status == TaskStatus.ASSIGNED


@pytest.mark.asyncio
async def test_recommendation_ranks_stay_unique_across_passes(
    client: AsyncClient, db: AsyncSession, fleet, offline_claude
) -> None:
    """A second pass must re-rank the cards already on screen, not collide.

    Regression: rank was the index within one pass, so when a bigger signal
    arrived later it took rank 0 while the surviving card from the earlier
    pass - now the second-biggest - kept rank 0 as well.
    """
    now = datetime.now(UTC)
    first_task = (await db.execute(sa.select(Task))).scalar_one()
    first_task.due_at = now + timedelta(minutes=10)
    first_task.eta = now + timedelta(minutes=30)  # 20 minutes over
    await db.commit()

    await client.post("/api/v1/copilot/run", headers=auth(fleet["admin"]))

    # A worse delay turns up after the first pass, so the ordering flips.
    db.add(
        Task(
            organization_id=fleet["org"].id,
            title="Depot run",
            driver_id=fleet["driver"].id,
            vehicle_id=fleet["vehicle"].id,
            destination_latitude=52.37,
            destination_longitude=4.90,
            status=TaskStatus.ASSIGNED,
            due_at=now + timedelta(minutes=10),
            eta=now + timedelta(minutes=100),  # 90 minutes over
        )
    )
    await db.commit()

    await client.post("/api/v1/copilot/run", headers=auth(fleet["admin"]))
    cards = (
        await client.get("/api/v1/copilot/recommendations", headers=auth(fleet["admin"]))
    ).json()

    titles = [card["title"] for card in cards]
    assert len(cards) == 2, titles
    ranks = [card["rank"] for card in cards]
    assert len(ranks) == len(set(ranks)), f"ranks collided: {list(zip(titles, ranks, strict=True))}"
    # The worse delay must now sort first.
    assert "Depot run" in titles[0]


def test_a_period_with_no_cost_records_says_so_rather_than_reporting_zero() -> None:
    """"Total cost 0.00" reads as a claim about spending. It is not one."""
    metrics = {
        "period": {"from": "2026-09-04", "to": "2026-09-11"},
        "distance_km": 4051.0,
        "trips": 38,
        "total_cost": 0.0,
        "cost_per_km": None,
        "fuel_cost": 0.0,
        "maintenance_cost": 0.0,
        "utilisation_percent": 86.0,
        "co2_kg": 0.0,
        "violations": 3,
        "average_safety_score": 81.0,
        "active_alerts": 12,
        "previous_period": {"distance_km": 3900.0, "violations": 4},
    }
    text = reports._offline_report(metrics)
    assert "No fuel or maintenance costs were recorded" in text
    assert "0.00" not in text
    assert "cannot be estimated" in text

    priced = reports._offline_report(
        {
            **metrics,
            "total_cost": 3057.18,
            "cost_per_km": 0.21,
            "fuel_cost": 1500.0,
            "maintenance_cost": 1557.18,
            "co2_kg": 1042.0,
        }
    )
    assert "Total cost was 3,057.18 (0.210 per km)" in priced
    assert "and the fleet emitted 1,042 kg" in priced
