"""Driver scoring, points, analytics and sustainability (Phase 4).

Sections 4g, 4.10, 4.13, 4.15, 4.17 and 5 items 1 and 4.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.anomaly import find_outliers
from app.ai.scoring import assess_fatigue, compute_safety_score
from app.models.driver import Driver, DriverEvent, PointsLedgerEntry
from app.models.enums import DriverEventType, TripStatus, UserRole
from app.models.fuel import FuelLog
from app.models.tracking import Trip
from app.models.vehicle import Vehicle
from app.services import rewards
from tests.conftest import auth, login, make_organization, make_user

# ---------------------------------------------------------------------------
# Pure scoring logic
# ---------------------------------------------------------------------------

def test_score_normalises_by_distance() -> None:
    """A long-haul driver must not be punished simply for driving more."""
    driver = uuid.uuid4()
    short = compute_safety_score(
        driver_id=driver, violations={"speeding": 5}, distance_km=500
    )
    long = compute_safety_score(
        driver_id=driver, violations={"speeding": 10}, distance_km=1000
    )
    # Same rate per 100 km -> same score, despite twice the raw violations.
    assert short.score == long.score


def test_score_stays_provisional_on_thin_data() -> None:
    """Two events over a short distance must not read as a terrible driver."""
    thin = compute_safety_score(
        driver_id=uuid.uuid4(), violations={"speeding": 3}, distance_km=30
    )
    assert thin.provisional is True
    assert thin.score == 100.0

    # The same event rate over a meaningful distance is scored for real.
    real = compute_safety_score(
        driver_id=uuid.uuid4(), violations={"speeding": 30}, distance_km=300
    )
    assert real.provisional is False
    assert real.score < 50


def test_score_bands_separate_drivers() -> None:
    driver = uuid.uuid4()
    clean = compute_safety_score(driver_id=driver, violations={}, distance_km=2000)
    poor = compute_safety_score(
        driver_id=driver,
        violations={"speeding": 40, "harsh_braking": 30},
        distance_km=1000,
    )
    assert clean.band == "excellent"
    assert poor.band == "at_risk"
    assert poor.score < clean.score


def test_fatigue_treats_a_short_stop_as_one_stint() -> None:
    """A delivery stop is not a rest break."""
    now = datetime.now(UTC)
    trips = [
        (now - timedelta(hours=6), now - timedelta(hours=3, minutes=10)),
        (now - timedelta(hours=3), now - timedelta(minutes=30)),
    ]
    result = assess_fatigue(
        driver_id=uuid.uuid4(),
        trips=trips,
        max_continuous_hours=4.5,
        min_rest_hours=8.0,
        now=now,
    )
    assert result.longest_continuous_hours > 5
    assert result.level in {"moderate", "high"}
    assert result.reasons


def test_fatigue_is_low_for_a_normal_day() -> None:
    now = datetime.now(UTC)
    result = assess_fatigue(
        driver_id=uuid.uuid4(),
        trips=[(now - timedelta(hours=3), now - timedelta(hours=1))],
        max_continuous_hours=4.5,
        min_rest_hours=8.0,
        now=now,
    )
    assert result.level == "low"
    assert result.reasons == []


def test_anomaly_baseline_excludes_the_sample_being_judged() -> None:
    """One extreme reading must not be able to hide inside its own mean."""
    now = datetime.now(UTC)
    samples = [(uuid.uuid4(), value, now) for value in [50, 52, 48, 51, 49, 130]]
    outliers = find_outliers(samples)
    assert len(outliers) == 1
    assert outliers[0][1] == 130


# ---------------------------------------------------------------------------
# Points, badges and the leaderboard
# ---------------------------------------------------------------------------

@pytest.fixture
async def fleet(client: AsyncClient, db: AsyncSession):
    org = await make_organization(db, "Acme Logistics")
    await make_user(
        db, email="admin@acme.example.com", role=UserRole.ORG_ADMIN, organization=org
    )
    driver_user = await make_user(
        db, email="dee@acme.example.com", role=UserRole.DRIVER, organization=org
    )

    vehicle = Vehicle(
        organization_id=org.id,
        name="Van 01",
        license_plate="ACM-001",
        odometer_km=40_000,
        purchase_value=30_000,
        residual_value=5_000,
        useful_life_years=5,
        purchase_date=date.today() - timedelta(days=365 * 6),
    )
    db.add(vehicle)
    await db.flush()

    dee = Driver(
        organization_id=org.id,
        user_id=driver_user.id,
        full_name="Dee Driver",
        assigned_vehicle_id=vehicle.id,
    )
    sam = Driver(organization_id=org.id, full_name="Sam Roads")
    db.add_all([dee, sam])
    await db.commit()

    return {
        "org": org,
        "vehicle": vehicle,
        "dee": dee,
        "sam": sam,
        "admin": await login(client, "admin@acme.example.com"),
        "driver_token": await login(client, "dee@acme.example.com"),
    }


async def _add_event(
    db: AsyncSession, fleet, event_type: str, *, when: datetime | None = None
) -> None:
    db.add(
        DriverEvent(
            organization_id=fleet["org"].id,
            driver_id=fleet["dee"].id,
            vehicle_id=fleet["vehicle"].id,
            event_type=event_type,
            severity="warning",
            occurred_at=when or datetime.now(UTC),
        )
    )
    await db.flush()


@pytest.mark.asyncio
async def test_events_become_points_using_org_weights(
    db: AsyncSession, fleet
) -> None:
    """Section 9: the weights are configuration, never hardcoded logic."""
    await _add_event(db, fleet, DriverEventType.SPEEDING)
    await _add_event(db, fleet, DriverEventType.HARSH_BRAKING)

    outcomes = await rewards.apply_pending_events(db, fleet["org"].id)
    await db.commit()

    assert len(outcomes) == 1
    # Defaults: speeding -5, harsh braking -3, from a baseline of 100.
    assert outcomes[0].delta == -8
    await db.refresh(fleet["dee"])
    assert fleet["dee"].points_balance == 92

    entries = (
        await db.execute(
            sa.select(PointsLedgerEntry).order_by(PointsLedgerEntry.created_at)
        )
    ).scalars().all()
    assert len(entries) == 2
    assert entries[-1].balance_after == 92
    # Every change is explainable.
    assert "Speeding" in entries[0].reason or "Harsh" in entries[0].reason


@pytest.mark.asyncio
async def test_tuned_weights_are_honoured(
    client: AsyncClient, db: AsyncSession, fleet
) -> None:
    await client.patch(
        "/api/v1/organization/settings",
        headers=auth(fleet["admin"]),
        json={"point_weights": {"speeding": -25}},
    )
    await _add_event(db, fleet, DriverEventType.SPEEDING)

    outcomes = await rewards.apply_pending_events(db, fleet["org"].id)
    assert outcomes[0].delta == -25


@pytest.mark.asyncio
async def test_events_are_applied_exactly_once(db: AsyncSession, fleet) -> None:
    await _add_event(db, fleet, DriverEventType.SPEEDING)

    assert len(await rewards.apply_pending_events(db, fleet["org"].id)) == 1
    # Re-running the pass must not double-charge the driver.
    assert await rewards.apply_pending_events(db, fleet["org"].id) == []

    await db.refresh(fleet["dee"])
    assert fleet["dee"].points_balance == 95


@pytest.mark.asyncio
async def test_points_floor_at_zero(db: AsyncSession, fleet) -> None:
    """A balance that can go negative stops motivating anyone."""
    for _ in range(30):
        await _add_event(db, fleet, DriverEventType.SPEEDING)

    await rewards.apply_pending_events(db, fleet["org"].id)
    await db.refresh(fleet["dee"])
    assert fleet["dee"].points_balance == 0

    entries = (
        await db.execute(sa.select(PointsLedgerEntry))
    ).scalars().all()
    assert all(entry.balance_after >= 0 for entry in entries)


@pytest.mark.asyncio
async def test_clean_streak_rewards_only_drivers_who_actually_drove(
    db: AsyncSession, fleet
) -> None:
    now = datetime.now(UTC)
    db.add(
        Trip(
            organization_id=fleet["org"].id,
            vehicle_id=fleet["vehicle"].id,
            driver_id=fleet["dee"].id,
            status=TripStatus.COMPLETED,
            started_at=now - timedelta(days=2),
            ended_at=now - timedelta(days=2, hours=-1),
            distance_km=120,
        )
    )
    await db.flush()

    awarded = await rewards.award_clean_streaks(db, fleet["org"].id)
    await db.commit()

    # Dee drove and stayed clean; Sam did not drive at all.
    assert [driver_id for driver_id, _ in awarded] == [fleet["dee"].id]
    await db.refresh(fleet["dee"])
    assert fleet["dee"].points_balance == 110

    # The badge is granted once per period, not on every pass.
    assert await rewards.award_clean_streaks(db, fleet["org"].id) == []


@pytest.mark.asyncio
async def test_a_violation_breaks_the_streak(db: AsyncSession, fleet) -> None:
    now = datetime.now(UTC)
    db.add(
        Trip(
            organization_id=fleet["org"].id,
            vehicle_id=fleet["vehicle"].id,
            driver_id=fleet["dee"].id,
            status=TripStatus.COMPLETED,
            started_at=now - timedelta(days=2),
            distance_km=120,
        )
    )
    await _add_event(db, fleet, DriverEventType.SPEEDING, when=now - timedelta(days=1))

    assert await rewards.award_clean_streaks(db, fleet["org"].id) == []


@pytest.mark.asyncio
async def test_leaderboard_ranks_and_shares_ties(
    client: AsyncClient, db: AsyncSession, fleet
) -> None:
    fleet["dee"].points_balance = 140
    fleet["sam"].points_balance = 140
    await db.commit()

    response = await client.get("/api/v1/leaderboard", headers=auth(fleet["admin"]))
    assert response.status_code == 200
    rows = response.json()["rows"]
    assert [row["rank"] for row in rows] == [1, 1]
    assert response.json()["visible_to_drivers"] is False
    assert len(response.json()["badge_catalogue"]) >= 3


@pytest.mark.asyncio
async def test_driver_sees_only_themselves_until_the_org_opts_in(
    client: AsyncClient, db: AsyncSession, fleet
) -> None:
    """Section 4g: peer visibility is the Org Admin's decision, default off."""
    hidden = await client.get(
        "/api/v1/leaderboard", headers=auth(fleet["driver_token"])
    )
    names = [row["driver_name"] for row in hidden.json()["rows"]]
    assert names == ["Dee Driver"]

    await client.patch(
        "/api/v1/organization/settings",
        headers=auth(fleet["admin"]),
        json={"show_leaderboard_to_drivers": True},
    )
    shown = await client.get(
        "/api/v1/leaderboard", headers=auth(fleet["driver_token"])
    )
    assert {row["driver_name"] for row in shown.json()["rows"]} == {
        "Dee Driver",
        "Sam Roads",
    }


@pytest.mark.asyncio
async def test_a_driver_cannot_read_another_drivers_points_history(
    client: AsyncClient, fleet
) -> None:
    mine = await client.get(
        f"/api/v1/drivers/{fleet['dee'].id}/points",
        headers=auth(fleet["driver_token"]),
    )
    assert mine.status_code == 200

    theirs = await client.get(
        f"/api/v1/drivers/{fleet['sam'].id}/points",
        headers=auth(fleet["driver_token"]),
    )
    assert theirs.status_code == 403


@pytest.mark.asyncio
async def test_monthly_reset_returns_to_baseline_but_keeps_the_ledger(
    db: AsyncSession, fleet
) -> None:
    fleet["dee"].points_balance = 61
    fleet["dee"].points_month = "2025-01"
    await db.commit()

    reset = await rewards.reset_monthly_balances(db, fleet["org"].id)
    await db.commit()
    assert reset >= 1

    await db.refresh(fleet["dee"])
    assert fleet["dee"].points_balance == 100
    # History survives the reset, so a driver can still see how they got there.
    entries = (await db.execute(sa.select(PointsLedgerEntry))).scalars().all()
    assert any("Monthly reset" in entry.reason for entry in entries)


# ---------------------------------------------------------------------------
# Analytics, cost and sustainability
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_costs_combine_fuel_maintenance_and_compliance(
    client: AsyncClient, db: AsyncSession, fleet
) -> None:
    token = fleet["admin"]
    now = datetime.now(UTC)

    await client.post(
        "/api/v1/fuel/logs",
        headers=auth(token),
        json={
            "vehicle_id": str(fleet["vehicle"].id),
            "fuel_type": "diesel",
            "quantity": 60,
            "total_cost": 102,
            "odometer_km": 40_500,
            "filled_at": now.isoformat(),
        },
    )
    work_order = (
        await client.post(
            "/api/v1/maintenance/work-orders",
            headers=auth(token),
            json={"vehicle_id": str(fleet["vehicle"].id), "title": "Brake pads"},
        )
    ).json()
    await client.patch(
        f"/api/v1/maintenance/work-orders/{work_order['id']}",
        headers=auth(token),
        json={"status": "completed", "labour_cost": 90, "parts_cost": 60},
    )

    response = await client.get("/api/v1/analytics/costs", headers=auth(token))
    assert response.status_code == 200
    row = response.json()[0]
    assert row["fuel_cost"] == 102
    assert row["maintenance_cost"] == 150
    assert row["total_cost"] == 252
    # Straight-line: (30000 - 5000) / 5 years, apportioned to the window.
    assert row["depreciation"] > 0


@pytest.mark.asyncio
async def test_kpis_report_utilisation_and_averages(
    client: AsyncClient, db: AsyncSession, fleet
) -> None:
    now = datetime.now(UTC)
    db.add(
        Trip(
            organization_id=fleet["org"].id,
            vehicle_id=fleet["vehicle"].id,
            driver_id=fleet["dee"].id,
            status=TripStatus.COMPLETED,
            started_at=now - timedelta(hours=3),
            ended_at=now - timedelta(hours=1),
            distance_km=88.0,
            duration_seconds=7200,
        )
    )
    await db.commit()

    response = await client.get("/api/v1/analytics/kpis", headers=auth(fleet["admin"]))
    body = response.json()
    assert body["trips"] == 1
    assert body["distance_km"] == 88.0
    assert body["driving_hours"] == 2.0
    assert body["utilisation_percent"] == 100.0
    assert body["total_vehicles"] == 1


@pytest.mark.asyncio
async def test_ev_advisor_judges_the_worst_day_not_the_average(
    client: AsyncClient, db: AsyncSession, fleet
) -> None:
    """A van that averages 90 km but hits 400 km once would strand a driver."""
    now = datetime.now(UTC)
    for day in range(30):
        db.add(
            Trip(
                organization_id=fleet["org"].id,
                vehicle_id=fleet["vehicle"].id,
                driver_id=fleet["dee"].id,
                status=TripStatus.COMPLETED,
                started_at=now - timedelta(days=day, hours=2),
                ended_at=now - timedelta(days=day, hours=1),
                distance_km=90.0,
            )
        )
    await db.commit()

    good = await client.get(
        "/api/v1/analytics/ev-candidates", headers=auth(fleet["admin"])
    )
    assert [row["vehicle_name"] for row in good.json()] == ["Van 01"]

    # One long day is enough to disqualify it.
    db.add(
        Trip(
            organization_id=fleet["org"].id,
            vehicle_id=fleet["vehicle"].id,
            driver_id=fleet["dee"].id,
            status=TripStatus.COMPLETED,
            started_at=now - timedelta(days=40),
            distance_km=400.0,
        )
    )
    await db.commit()

    after = await client.get(
        "/api/v1/analytics/ev-candidates", headers=auth(fleet["admin"])
    )
    assert after.json() == []


@pytest.mark.asyncio
async def test_asset_lifecycle_flags_a_vehicle_past_its_life(
    client: AsyncClient, fleet
) -> None:
    response = await client.get("/api/v1/analytics/assets", headers=auth(fleet["admin"]))
    row = response.json()[0]
    assert row["replacement_recommended"] is True
    assert any("useful life" in reason for reason in row["reasons"])
    assert row["annual_depreciation"] == 5000.0


@pytest.mark.asyncio
async def test_anomaly_endpoint_flags_an_unusual_fill_up(
    client: AsyncClient, db: AsyncSession, fleet
) -> None:
    now = datetime.now(UTC)
    for index, quantity in enumerate([50, 52, 48, 51, 49, 140]):
        db.add(
            FuelLog(
                organization_id=fleet["org"].id,
                vehicle_id=fleet["vehicle"].id,
                fuel_type="diesel",
                quantity=quantity,
                unit="L",
                total_cost=quantity * 1.7,
                filled_at=now - timedelta(days=30 - index),
            )
        )
    await db.commit()

    response = await client.get(
        "/api/v1/analytics/anomalies", headers=auth(fleet["admin"])
    )
    fuel = [a for a in response.json() if a["kind"] == "fuel_consumption"]
    assert len(fuel) == 1
    assert fuel[0]["value"] == 140
    assert "standard deviations" in fuel[0]["summary"]


@pytest.mark.asyncio
async def test_maintenance_forecast_projects_from_recent_usage(
    client: AsyncClient, db: AsyncSession, fleet
) -> None:
    token = fleet["admin"]
    now = datetime.now(UTC)

    # 100 km/day for the last 10 days.
    for day in range(10):
        db.add(
            Trip(
                organization_id=fleet["org"].id,
                vehicle_id=fleet["vehicle"].id,
                driver_id=fleet["dee"].id,
                status=TripStatus.COMPLETED,
                started_at=now - timedelta(days=day, hours=2),
                distance_km=300.0,
            )
        )
    await db.commit()

    await client.post(
        "/api/v1/maintenance/schedules",
        headers=auth(token),
        json={
            "vehicle_id": str(fleet["vehicle"].id),
            "name": "Oil change",
            "interval_type": "mileage",
            "interval_km": 10_000,
            # Due at 42,000 km; the vehicle is at 40,000 and covering
            # ~100 km/day, so it lands ~20 days out - inside the horizon.
            "last_service_odometer_km": 32_000,
        },
    )

    response = await client.get(
        "/api/v1/analytics/maintenance-forecast", headers=auth(token)
    )
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["schedule_name"] == "Oil change"
    assert rows[0]["daily_km"] == pytest.approx(100.0, abs=1.0)
    assert rows[0]["remaining_km"] == pytest.approx(2000.0, abs=1.0)
    assert 15 <= rows[0]["days_away"] <= 25
    assert "km/day" in rows[0]["basis"]


@pytest.mark.asyncio
async def test_cost_per_km_is_withheld_below_a_usable_distance(
    client: AsyncClient, db: AsyncSession, fleet
) -> None:
    """25 km and a gearbox rebuild is not a per-km figure worth showing."""
    now = datetime.now(UTC)
    db.add(
        Trip(
            organization_id=fleet["org"].id,
            vehicle_id=fleet["vehicle"].id,
            driver_id=fleet["dee"].id,
            status=TripStatus.COMPLETED,
            started_at=now - timedelta(hours=2),
            distance_km=25.0,
        )
    )
    await db.commit()
    await client.post(
        "/api/v1/fuel/logs",
        headers=auth(fleet["admin"]),
        json={
            "vehicle_id": str(fleet["vehicle"].id),
            "fuel_type": "diesel",
            "quantity": 60,
            "total_cost": 480,
            "filled_at": now.isoformat(),
        },
    )

    thin = await client.get("/api/v1/analytics/costs", headers=auth(fleet["admin"]))
    assert thin.json()[0]["total_cost"] == 480
    assert thin.json()[0]["cost_per_km"] is None

    db.add(
        Trip(
            organization_id=fleet["org"].id,
            vehicle_id=fleet["vehicle"].id,
            driver_id=fleet["dee"].id,
            status=TripStatus.COMPLETED,
            started_at=now - timedelta(hours=6),
            distance_km=575.0,
        )
    )
    await db.commit()

    usable = await client.get("/api/v1/analytics/costs", headers=auth(fleet["admin"]))
    assert usable.json()[0]["cost_per_km"] == pytest.approx(0.8, abs=0.01)


@pytest.mark.asyncio
async def test_analytics_are_tenant_scoped(
    client: AsyncClient, db: AsyncSession, fleet
) -> None:
    rival = await make_organization(db, "Rival Freight")
    await make_user(
        db, email="rex@rival.example.com", role=UserRole.ORG_ADMIN, organization=rival
    )
    await db.commit()
    token = await login(client, "rex@rival.example.com")

    assert (
        await client.get("/api/v1/analytics/costs", headers=auth(token))
    ).json() == []
    assert (
        await client.get("/api/v1/leaderboard", headers=auth(token))
    ).json()["rows"] == []
    kpis = await client.get("/api/v1/analytics/kpis", headers=auth(token))
    assert kpis.json()["total_vehicles"] == 0


@pytest.mark.asyncio
async def test_recompute_endpoint_runs_the_whole_pass(
    client: AsyncClient, db: AsyncSession, fleet
) -> None:
    await _add_event(db, fleet, DriverEventType.SPEEDING)
    await db.commit()

    response = await client.post(
        "/api/v1/analytics/recompute", headers=auth(fleet["admin"])
    )
    assert response.status_code == 200
    assert response.json()["drivers_scored"] == 2
    assert response.json()["drivers_with_points_changes"] == 1
