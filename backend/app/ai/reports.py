"""Automated report summaries (Section 5, item 5).

The metrics are computed by our own analytics code; the model writes the
paragraph. Without an API key the report still generates - it just reads as
figures rather than prose, which is the right failure: a weekly report that
silently stops arriving is worse than one that arrives plainly worded.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import get_claude_client
from app.core.tenancy import TenantScope
from app.models.ai import ReportSummary
from app.services import analytics


def utcnow() -> datetime:
    return datetime.now(UTC)


PERIODS = {"weekly": 7, "monthly": 30}


async def generate_summary(
    db: AsyncSession,
    scope: TenantScope,
    *,
    period_type: str = "weekly",
    now: datetime | None = None,
) -> ReportSummary:
    """Build the period's metrics and write them up."""
    moment = now or utcnow()
    days = PERIODS.get(period_type, 7)
    end = moment.date()
    start = end - timedelta(days=days)

    kpis = await analytics.fleet_kpis(db, scope, date_from=start, date_to=end)
    costs = await analytics.vehicle_costs(db, scope, date_from=start, date_to=end)
    top = sorted(costs, key=lambda c: c.total_cost, reverse=True)[:3]

    previous = await analytics.fleet_kpis(
        db, scope, date_from=start - timedelta(days=days), date_to=start
    )

    metrics = {
        "period": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "distance_km": kpis.distance_km,
        "trips": kpis.trips,
        "utilisation_percent": kpis.utilisation_percent,
        "total_cost": kpis.total_cost,
        "cost_per_km": kpis.cost_per_km,
        "fuel_cost": kpis.fuel_cost,
        "maintenance_cost": kpis.maintenance_cost,
        "co2_kg": kpis.co2_kg,
        "violations": kpis.violations,
        "average_safety_score": kpis.average_safety_score,
        "active_alerts": kpis.active_alerts,
        "previous_period": {
            "distance_km": previous.distance_km,
            "total_cost": previous.total_cost,
            "violations": previous.violations,
        },
        "top_cost_vehicles": [
            {"name": c.vehicle_name, "total_cost": c.total_cost} for c in top
        ],
    }

    response = await get_claude_client().complete(
        organization_id=scope.organization_id,
        system=(
            "You write a short weekly fleet report for an operations manager. "
            "Four or five sentences. Lead with what changed against the "
            "previous period, then cost, then safety. Use ONLY the figures "
            "given - never invent one - and say plainly when a figure is zero "
            "rather than dressing it up."
        ),
        prompt=f"Metrics:\n{json.dumps(metrics, default=str)}",
        offline_text=_offline_report(metrics),
        max_tokens=800,
        effort="low",
    )

    summary = ReportSummary(
        organization_id=scope.organization_id,
        period_type=period_type,
        period_start=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        period_end=datetime.combine(end, datetime.min.time(), tzinfo=UTC),
        summary_text=response.text,
        metrics=metrics,
        generated_by="rule_based" if response.fallback else response.model,
    )
    db.add(summary)
    await db.flush()
    return summary


def _offline_report(metrics: dict) -> str:
    """The same report, written by arithmetic instead of a model."""
    previous = metrics["previous_period"]

    def delta(current: float, before: float, unit: str = "") -> str:
        if before == 0:
            return "no comparable figure for the previous period"
        change = (current - before) / before * 100
        direction = "up" if change >= 0 else "down"
        return f"{direction} {abs(change):.0f}%{unit} on the previous period"

    return (
        f"Between {metrics['period']['from']} and {metrics['period']['to']} the "
        f"fleet covered {metrics['distance_km']:,.0f} km over "
        f"{metrics['trips']} trips - "
        f"{delta(metrics['distance_km'], previous['distance_km'])}. "
        f"Total cost was {metrics['total_cost']:,.2f}"
        + (
            f" ({metrics['cost_per_km']:.3f} per km)"
            if metrics["cost_per_km"] is not None
            else ""
        )
        + f", of which {metrics['fuel_cost']:,.2f} was fuel and "
        f"{metrics['maintenance_cost']:,.2f} maintenance. "
        f"Vehicle utilisation was {metrics['utilisation_percent']:.0f}%, and the "
        f"fleet emitted {metrics['co2_kg']:,.0f} kg of CO2. "
        f"There were {metrics['violations']} driving violations "
        f"({delta(metrics['violations'], previous['violations'])}), with an "
        f"average driver safety score of {metrics['average_safety_score']:.0f} "
        f"and {metrics['active_alerts']} alerts still open."
    )


async def list_summaries(
    db: AsyncSession, scope: TenantScope, *, limit: int = 12
) -> list[ReportSummary]:
    result = await db.execute(
        scope.select(ReportSummary)
        .order_by(ReportSummary.period_end.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
