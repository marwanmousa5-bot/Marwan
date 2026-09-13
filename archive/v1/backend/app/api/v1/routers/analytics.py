"""Analytics, cost/TCO, sustainability and driver rewards APIs."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import anomaly as anomaly_service
from app.ai import predictive, scoring
from app.core.deps import (
    Principal,
    get_current_principal,
    get_tenant_scope,
    require_dashboard_user,
    require_org_admin,
)
from app.core.errors import PermissionDeniedError
from app.core.tenancy import TenantScope
from app.db.session import get_db
from app.models.enums import UserRole
from app.schemas.analytics import (
    AnomalyOut,
    AssetSummaryOut,
    BadgeDefinition,
    DriverScoreOut,
    EvCandidateOut,
    FleetKpisOut,
    LeaderboardOut,
    LeaderboardRow,
    MaintenanceForecastOut,
    PointsLedgerEntryOut,
    TrendPointOut,
    VehicleCostOut,
)
from app.services import analytics, rewards
from app.services.alerts import settings_for

router = APIRouter(tags=["analytics"])

#: Default reporting window when the caller does not supply one.
DEFAULT_PERIOD_DAYS = 30


def _range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    end = date_to or datetime.now(UTC).date()
    start = date_from or end - timedelta(days=DEFAULT_PERIOD_DAYS)
    return start, end


@router.get(
    "/analytics/kpis",
    response_model=FleetKpisOut,
    summary="Headline fleet KPIs for a period",
)
async def fleet_kpis(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> FleetKpisOut:
    start, end = _range(date_from, date_to)
    kpis = await analytics.fleet_kpis(db, scope, date_from=start, date_to=end)
    return FleetKpisOut(**asdict(kpis))


@router.get(
    "/analytics/costs",
    response_model=list[VehicleCostOut],
    summary="Cost and TCO per vehicle (Section 4 item 10)",
)
async def vehicle_costs(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[VehicleCostOut]:
    start, end = _range(date_from, date_to)
    rows = await analytics.vehicle_costs(db, scope, date_from=start, date_to=end)
    return [
        VehicleCostOut(
            vehicle_id=row.vehicle_id,
            vehicle_name=row.vehicle_name,
            license_plate=row.license_plate,
            fuel_cost=round(row.fuel_cost, 2),
            maintenance_cost=round(row.maintenance_cost, 2),
            compliance_cost=round(row.compliance_cost, 2),
            depreciation=row.depreciation,
            total_cost=row.total_cost,
            distance_km=row.distance_km,
            cost_per_km=row.cost_per_km,
        )
        for row in rows
    ]


@router.get(
    "/analytics/trends",
    response_model=list[TrendPointOut],
    summary="Monthly distance, cost, CO2 and violation trends",
)
async def trends(
    months: int = Query(default=6, ge=1, le=24),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[TrendPointOut]:
    points = await analytics.monthly_trends(db, scope, months=months)
    return [TrendPointOut(**asdict(p)) for p in points]


@router.get(
    "/analytics/ev-candidates",
    response_model=list[EvCandidateOut],
    summary="EV Transition Advisor (Section 4 item 17)",
)
async def ev_candidates(
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[EvCandidateOut]:
    rows = await analytics.ev_transition_candidates(db, scope)
    return [EvCandidateOut(**asdict(row)) for row in rows]


@router.get(
    "/analytics/assets",
    response_model=list[AssetSummaryOut],
    summary="Asset lifecycle and replacement flags (Section 4 item 15)",
)
async def assets(
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[AssetSummaryOut]:
    rows = await analytics.asset_lifecycle(db, scope)
    return [AssetSummaryOut(**asdict(row)) for row in rows]


@router.get(
    "/analytics/anomalies",
    response_model=list[AnomalyOut],
    summary="Statistically unusual fuel and idle patterns (Section 5 item 4)",
)
async def anomalies(
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[AnomalyOut]:
    found = [
        *await anomaly_service.detect_fuel_anomalies(db, scope.organization_id),
        *await anomaly_service.detect_idle_anomalies(db, scope.organization_id),
    ]
    return [
        AnomalyOut(
            kind=a.kind,
            vehicle_id=a.vehicle_id,
            vehicle_name=a.vehicle_name,
            value=a.value,
            mean=a.mean,
            z_score=a.z_score,
            summary=a.summary,
            observed_at=a.observed_at,
        )
        for a in found
    ]


@router.get(
    "/analytics/maintenance-forecast",
    response_model=list[MaintenanceForecastOut],
    summary="Predictive maintenance: what falls due soon and why",
)
async def maintenance_forecast(
    horizon_days: int = Query(default=30, ge=1, le=180),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[MaintenanceForecastOut]:
    rows = await predictive.forecast_due_maintenance(
        db, scope.organization_id, horizon_days=horizon_days
    )
    return [
        MaintenanceForecastOut(**asdict(row), summary=row.summary) for row in rows
    ]


# ---------------------------------------------------------------------------
# Driver scores and rewards (Sections 4g and 5 item 1)
# ---------------------------------------------------------------------------

# Deliberately not "/drivers/scores": the drivers router already owns
# "/drivers/{driver_id}", and a literal segment registered after a path
# parameter is shadowed by it - FastAPI would try to parse "scores" as a UUID.
@router.get(
    "/analytics/driver-scores",
    response_model=list[DriverScoreOut],
    summary="Safety scores and fatigue risk per driver",
)
async def driver_scores(
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[DriverScoreOut]:
    results = await scoring.score_organization_drivers(db, scope.organization_id)
    return [
        DriverScoreOut(
            driver_id=driver.id,
            driver_name=driver.full_name,
            safety_score=score.score,
            score_band=score.band,
            provisional=score.provisional,
            distance_km=score.distance_km,
            violations=score.violations,
            fatigue_risk_level=fatigue.level,
            fatigue_reasons=fatigue.reasons,
            points_balance=driver.points_balance,
        )
        for driver, score, fatigue in results
    ]


@router.get(
    "/leaderboard",
    response_model=LeaderboardOut,
    summary="Monthly driver leaderboard (Section 4g)",
)
async def leaderboard(
    principal: Principal = Depends(get_current_principal),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> LeaderboardOut:
    """Visible to staff always; to drivers only if the Organization opts in.

    When a driver's Organization has peer visibility switched off they still
    get their own standing back - just not anyone else's (Section 4g).
    """
    settings_row = await settings_for(db, scope.organization_id)
    visible_to_drivers = bool(
        settings_row and settings_row.show_leaderboard_to_drivers
    )

    if principal.role == UserRole.DRIVER and not visible_to_drivers:
        from app.services.tasks import driver_for_user

        driver = await driver_for_user(db, scope, user_id=principal.user_id)
        rows = [
            row
            for row in await rewards.leaderboard(db, scope)
            if row["driver_id"] == driver.id
        ]
    else:
        rows = await rewards.leaderboard(db, scope)

    return LeaderboardOut(
        period=rewards.period_of(),
        rows=[LeaderboardRow(**row) for row in rows],
        badge_catalogue=[
            BadgeDefinition(code=code, **meta) for code, meta in rewards.BADGES.items()
        ],
        visible_to_drivers=visible_to_drivers,
    )


@router.get(
    "/drivers/{driver_id}/points",
    response_model=list[PointsLedgerEntryOut],
    summary="Why a driver's balance is what it is",
)
async def driver_points(
    driver_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[PointsLedgerEntryOut]:
    if principal.role == UserRole.DRIVER:
        from app.services.tasks import driver_for_user

        driver = await driver_for_user(db, scope, user_id=principal.user_id)
        if driver.id != driver_id:
            raise PermissionDeniedError("You can only view your own points history")

    entries = await rewards.driver_ledger(db, scope, driver_id=driver_id)
    return [PointsLedgerEntryOut.model_validate(e) for e in entries]


@router.post(
    "/analytics/recompute",
    response_model=dict,
    summary="Recompute scores and apply pending points now",
)
async def recompute(
    _: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manual trigger for the same work Celery beat does hourly."""
    scored = await scoring.score_organization_drivers(db, scope.organization_id)
    outcomes = await rewards.apply_pending_events(db, scope.organization_id)
    streaks = await rewards.award_clean_streaks(db, scope.organization_id)
    return {
        "drivers_scored": len(scored),
        "drivers_with_points_changes": len(outcomes),
        "clean_streaks_awarded": len(streaks),
    }
