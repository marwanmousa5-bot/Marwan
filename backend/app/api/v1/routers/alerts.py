"""Alerts feed and per-Organization rule configuration (Section 4 item 12)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    Principal,
    get_tenant_scope,
    require_dashboard_user,
    require_org_admin,
)
from app.core.tenancy import TenantScope
from app.db.session import get_db
from app.models.enums import AlertRuleType, AlertStatus
from app.models.weather import WeatherZone
from app.schemas.common import Page
from app.schemas.tracking import (
    AlertOut,
    AlertRuleOut,
    AlertRuleUpdate,
    WeatherZoneOut,
)
from app.services import alerts as alert_service

router = APIRouter(tags=["alerts"])


@router.get("/alerts", response_model=Page[AlertOut], summary="Alerts feed")
async def list_alerts(
    status_filter: AlertStatus | None = Query(default=AlertStatus.ACTIVE, alias="status"),
    vehicle_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Page[AlertOut]:
    items, total = await alert_service.list_alerts(
        db, scope, status=status_filter, vehicle_id=vehicle_id, limit=limit, offset=offset
    )
    return Page[AlertOut](
        items=[AlertOut.model_validate(a) for a in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/alerts/{alert_id}/acknowledge",
    response_model=AlertOut,
    summary="Acknowledge an alert",
)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> AlertOut:
    alert = await alert_service.set_alert_status(
        db,
        scope,
        alert_id=alert_id,
        status=AlertStatus.ACKNOWLEDGED,
        user_id=principal.user_id,
    )
    return AlertOut.model_validate(alert)


@router.post(
    "/alerts/{alert_id}/resolve", response_model=AlertOut, summary="Resolve an alert"
)
async def resolve_alert(
    alert_id: uuid.UUID,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> AlertOut:
    alert = await alert_service.set_alert_status(
        db,
        scope,
        alert_id=alert_id,
        status=AlertStatus.RESOLVED,
        user_id=principal.user_id,
    )
    return AlertOut.model_validate(alert)


@router.get(
    "/alert-rules",
    response_model=list[AlertRuleOut],
    summary="Alert rules configured for your organization",
)
async def list_alert_rules(
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[AlertRuleOut]:
    rules = await alert_service.list_rules(db, scope)
    return [AlertRuleOut.model_validate(r) for r in rules]


@router.patch(
    "/alert-rules/{rule_type}",
    response_model=AlertRuleOut,
    summary="Enable, disable or retune one alert rule",
)
async def update_alert_rule(
    rule_type: AlertRuleType,
    payload: AlertRuleUpdate,
    _: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> AlertRuleOut:
    rule = await alert_service.update_rule(
        db,
        scope,
        rule_type=rule_type,
        is_enabled=payload.is_enabled,
        severity=payload.severity,
        parameters=payload.parameters,
    )
    return AlertRuleOut.model_validate(rule)


@router.get(
    "/weather-zones",
    response_model=list[WeatherZoneOut],
    summary="Adverse-weather zones for the map overlay (Section 4e)",
)
async def list_weather_zones(
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[WeatherZoneOut]:
    result = await db.execute(
        scope.select(WeatherZone).order_by(WeatherZone.observed_at.desc())
    )
    return [WeatherZoneOut.model_validate(z) for z in result.scalars().all()]
