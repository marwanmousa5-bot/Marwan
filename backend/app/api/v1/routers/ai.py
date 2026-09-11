"""AI assistant, copilots, reporting and export (Sections 4e, 5, 4.13).

Every state-changing AI path in this router is two-step: propose, then apply
on an explicit confirmation. There is no endpoint that lets the model change
data in one call (Section 9).
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import assistant, copilot, reports
from app.core.deps import (
    Principal,
    get_tenant_scope,
    require_dashboard_user,
    require_org_admin,
)
from app.core.errors import NotFoundError, ValidationError
from app.core.tenancy import TenantScope
from app.db.session import get_db
from app.models.ai import Recommendation
from app.models.enums import AuditAction, RecommendationStatus, WorkOrderStatus
from app.schemas.ai import (
    AssistantActionResult,
    AssistantAsk,
    AssistantConfirm,
    AssistantReplyOut,
    MaintenanceProposalOut,
    RecommendationOut,
    ReportSummaryOut,
)
from app.services import analytics, audit, exports

router = APIRouter(tags=["ai"])


def utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Agentic assistant (Section 5 item 3)
# ---------------------------------------------------------------------------

@router.post(
    "/assistant/ask",
    response_model=AssistantReplyOut,
    summary="Ask about your fleet, or propose an action for confirmation",
)
async def ask(
    payload: AssistantAsk,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> AssistantReplyOut:
    reply = await assistant.ask(
        db, scope, question=payload.question, user_id=principal.user_id
    )
    return AssistantReplyOut(
        answer=reply.answer,
        capability=reply.capability,
        kind=reply.kind,
        data=reply.data,
        pending_action=reply.pending_action,
        offline=reply.offline,
    )


@router.post(
    "/assistant/confirm",
    response_model=AssistantActionResult,
    summary="Apply an action the assistant proposed (the only mutating path)",
)
async def confirm(
    payload: AssistantConfirm,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> AssistantActionResult:
    result = await assistant.confirm_action(
        db,
        scope,
        pending_action=payload.pending_action,
        user_id=principal.user_id,
        principal=principal,
        request=request,
    )
    return AssistantActionResult(**result)


# ---------------------------------------------------------------------------
# Fleet Copilot (Section 4e)
# ---------------------------------------------------------------------------

@router.get(
    "/copilot/recommendations",
    response_model=list[RecommendationOut],
    summary="Current Copilot recommendations",
)
async def list_recommendations(
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[RecommendationOut]:
    rows = await copilot.list_recommendations(db, scope.organization_id)
    return [RecommendationOut.model_validate(r) for r in rows]


@router.post(
    "/copilot/run",
    response_model=list[RecommendationOut],
    summary="Run an analysis pass now (also runs every 2 minutes on a schedule)",
)
async def run_copilot(
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[RecommendationOut]:
    await copilot.run_copilot(db, scope.organization_id)
    rows = await copilot.list_recommendations(db, scope.organization_id)
    return [RecommendationOut.model_validate(r) for r in rows]


@router.post(
    "/copilot/recommendations/{recommendation_id}/dismiss",
    response_model=RecommendationOut,
    summary="Dismiss a recommendation so it stops resurfacing",
)
async def dismiss(
    recommendation_id: uuid.UUID,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> RecommendationOut:
    recommendation = await scope.get_or_404(
        db, Recommendation, recommendation_id, label="Recommendation"
    )
    recommendation.status = RecommendationStatus.DISMISSED
    recommendation.dismissed_at = utcnow()
    recommendation.decided_by_user_id = principal.user_id
    return RecommendationOut.model_validate(recommendation)


@router.post(
    "/copilot/recommendations/{recommendation_id}/apply",
    response_model=RecommendationOut,
    summary="Apply a recommendation - always an explicit, separate step",
)
async def apply(
    recommendation_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> RecommendationOut:
    """Execute a recommendation's payload.

    The Copilot never reaches this endpoint by itself; a person does, after
    reading the card (Section 9).
    """
    recommendation = await scope.get_or_404(
        db, Recommendation, recommendation_id, label="Recommendation"
    )
    if recommendation.status != RecommendationStatus.PENDING:
        raise ValidationError("That recommendation has already been decided")

    payload = recommendation.action_payload or {}
    operation = payload.get("op")

    if operation == "assign_task":
        from app.services import tasks as task_service

        await task_service.reassign(
            db,
            scope,
            task_id=uuid.UUID(payload["task_id"]),
            driver_id=uuid.UUID(payload["driver_id"]),
            principal=principal,
            request=request,
        )
    elif operation == "create_work_order":
        from app.services import maintenance as maintenance_service

        scheduled = payload.get("scheduled_for")
        await maintenance_service.create_work_order(
            db,
            scope,
            data={
                "vehicle_id": uuid.UUID(payload["vehicle_id"]),
                "schedule_id": uuid.UUID(payload["schedule_id"]),
                "title": payload.get("title", "Scheduled maintenance"),
                "status": WorkOrderStatus.OPEN,
                "scheduled_for": (
                    datetime.combine(
                        date.fromisoformat(scheduled), datetime.min.time(), tzinfo=UTC
                    )
                    if scheduled
                    else None
                ),
                "description": recommendation.summary,
                "odometer_km": None,
                "vendor": None,
            },
            principal=principal,
            request=request,
        )
    else:
        raise ValidationError(
            "That recommendation is informational - there is nothing to apply."
        )

    recommendation.status = RecommendationStatus.APPLIED
    recommendation.applied_at = utcnow()
    recommendation.decided_by_user_id = principal.user_id

    await audit.record(
        db,
        action=AuditAction.AI_ACTION_CONFIRMED,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="recommendation",
        entity_id=recommendation.id,
        summary=f"Recommendation applied: {recommendation.title}",
        request=request,
    )
    return RecommendationOut.model_validate(recommendation)


@router.post(
    "/copilot/maintenance-windows",
    response_model=list[MaintenanceProposalOut],
    summary="Maintenance Copilot: propose the lowest-impact service window",
)
async def maintenance_windows(
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[MaintenanceProposalOut]:
    proposals = await copilot.propose_maintenance_windows(db, scope.organization_id)
    return [MaintenanceProposalOut(**asdict(p)) for p in proposals]


# ---------------------------------------------------------------------------
# Reporting and export (Sections 5 item 5, 4 item 13)
# ---------------------------------------------------------------------------

@router.get(
    "/reports/summaries",
    response_model=list[ReportSummaryOut],
    summary="Automated narrative fleet summaries",
)
async def list_summaries(
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[ReportSummaryOut]:
    rows = await reports.list_summaries(db, scope)
    return [ReportSummaryOut.model_validate(r) for r in rows]


@router.post(
    "/reports/summaries",
    response_model=ReportSummaryOut,
    summary="Generate a summary for the current period now",
)
async def generate_summary(
    period_type: str = Query(default="weekly", pattern="^(weekly|monthly)$"),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> ReportSummaryOut:
    summary = await reports.generate_summary(db, scope, period_type=period_type)
    return ReportSummaryOut.model_validate(summary)


@router.get(
    "/reports/costs.{fmt}",
    summary="Export the cost report as CSV or PDF",
    response_class=Response,
)
async def export_costs(
    fmt: str,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if fmt not in {"csv", "pdf"}:
        raise NotFoundError("Export format must be csv or pdf")

    end = date_to or utcnow().date()
    start = date_from or end - timedelta(days=30)
    rows = await analytics.vehicle_costs(db, scope, date_from=start, date_to=end)

    headers = ["Vehicle", "Plate", "Fuel", "Maintenance", "Compliance", "Total", "Per km"]
    table = [
        [
            row.vehicle_name,
            row.license_plate,
            f"{row.fuel_cost:.2f}",
            f"{row.maintenance_cost:.2f}",
            f"{row.compliance_cost:.2f}",
            f"{row.total_cost:.2f}",
            f"{row.cost_per_km:.3f}" if row.cost_per_km is not None else "",
        ]
        for row in rows
    ]
    filename = f"fleetbeat-costs-{start}-to-{end}"

    if fmt == "csv":
        return Response(
            content=exports.to_csv(headers, table),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}.csv"'
            },
        )

    return Response(
        content=exports.to_pdf(
            title="Fleet cost report",
            subtitle=f"{start} to {end}",
            headers=headers,
            rows=table,
            column_widths=[110, 70, 60, 85, 75, 60, 55],
        ),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )
