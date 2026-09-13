"""Maintenance, fuel/energy and compliance APIs (Section 4 items 6, 7, 9)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    Principal,
    get_tenant_scope,
    require_dashboard_user,
    require_org_admin,
)
from app.core.tenancy import TenantScope
from app.db.session import get_db
from app.models.enums import WorkOrderStatus
from app.schemas.common import Message, Page
from app.schemas.operations import (
    ComplianceDocumentCreate,
    ComplianceDocumentOut,
    ComplianceDocumentUpdate,
    FuelLogCreate,
    FuelLogOut,
    FuelSummary,
    MaintenanceScheduleCreate,
    MaintenanceScheduleOut,
    MaintenanceScheduleUpdate,
    ServiceRecordOut,
    WorkOrderCreate,
    WorkOrderOut,
    WorkOrderUpdate,
)
from app.services import compliance as compliance_service
from app.services import fuel as fuel_service
from app.services import maintenance as maintenance_service

router = APIRouter(tags=["operations"])


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

@router.get(
    "/maintenance/schedules",
    response_model=list[MaintenanceScheduleOut],
    summary="Preventive maintenance schedules",
)
async def list_schedules(
    vehicle_id: uuid.UUID | None = Query(default=None),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[MaintenanceScheduleOut]:
    rows = await maintenance_service.list_schedules(db, scope, vehicle_id=vehicle_id)
    return [MaintenanceScheduleOut.model_validate(r) for r in rows]


@router.post(
    "/maintenance/schedules",
    response_model=MaintenanceScheduleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a maintenance schedule",
)
async def create_schedule(
    payload: MaintenanceScheduleCreate,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> MaintenanceScheduleOut:
    schedule = await maintenance_service.create_schedule(
        db, scope, data=payload.model_dump(), principal=principal, request=request
    )
    return MaintenanceScheduleOut.model_validate(schedule)


@router.patch(
    "/maintenance/schedules/{schedule_id}",
    response_model=MaintenanceScheduleOut,
    summary="Update a maintenance schedule",
)
async def update_schedule(
    schedule_id: uuid.UUID,
    payload: MaintenanceScheduleUpdate,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> MaintenanceScheduleOut:
    schedule = await maintenance_service.update_schedule(
        db,
        scope,
        schedule_id=schedule_id,
        data=payload.model_dump(exclude_unset=True),
        principal=principal,
        request=request,
    )
    return MaintenanceScheduleOut.model_validate(schedule)


@router.get(
    "/maintenance/work-orders",
    response_model=Page[WorkOrderOut],
    summary="Work orders",
)
async def list_work_orders(
    vehicle_id: uuid.UUID | None = Query(default=None),
    status_filter: WorkOrderStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Page[WorkOrderOut]:
    items, total = await maintenance_service.list_work_orders(
        db, scope, vehicle_id=vehicle_id, status=status_filter, limit=limit, offset=offset
    )
    return Page[WorkOrderOut](
        items=[WorkOrderOut.model_validate(w) for w in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/maintenance/work-orders",
    response_model=WorkOrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Open a work order",
)
async def create_work_order(
    payload: WorkOrderCreate,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> WorkOrderOut:
    work_order = await maintenance_service.create_work_order(
        db, scope, data=payload.model_dump(), principal=principal, request=request
    )
    return WorkOrderOut.model_validate(work_order)


@router.patch(
    "/maintenance/work-orders/{work_order_id}",
    response_model=WorkOrderOut,
    summary="Update a work order (completing it writes service history)",
)
async def update_work_order(
    work_order_id: uuid.UUID,
    payload: WorkOrderUpdate,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> WorkOrderOut:
    work_order = await maintenance_service.update_work_order(
        db,
        scope,
        work_order_id=work_order_id,
        data=payload.model_dump(exclude_unset=True),
        principal=principal,
        request=request,
    )
    return WorkOrderOut.model_validate(work_order)


@router.get(
    "/maintenance/service-records",
    response_model=list[ServiceRecordOut],
    summary="Service history",
)
async def list_service_records(
    vehicle_id: uuid.UUID | None = Query(default=None),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[ServiceRecordOut]:
    rows = await maintenance_service.list_service_records(
        db, scope, vehicle_id=vehicle_id
    )
    return [ServiceRecordOut.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Fuel & energy
# ---------------------------------------------------------------------------

@router.get("/fuel/logs", response_model=Page[FuelLogOut], summary="Fuel log entries")
async def list_fuel_logs(
    vehicle_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Page[FuelLogOut]:
    items, total = await fuel_service.list_logs(
        db, scope, vehicle_id=vehicle_id, limit=limit, offset=offset
    )
    return Page[FuelLogOut](
        items=[FuelLogOut.model_validate(f) for f in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/fuel/logs",
    response_model=FuelLogOut,
    status_code=status.HTTP_201_CREATED,
    summary="Log a fill-up or charging session",
)
async def create_fuel_log(
    payload: FuelLogCreate,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> FuelLogOut:
    entry = await fuel_service.create_log(
        db, scope, data=payload.model_dump(), principal=principal, request=request
    )
    return FuelLogOut.model_validate(entry)


@router.get(
    "/fuel/summary",
    response_model=list[FuelSummary],
    summary="Consumption and CO2 per vehicle",
)
async def fuel_summary(
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[FuelSummary]:
    rows = await fuel_service.summarise(db, scope)
    return [
        FuelSummary(
            vehicle_id=vehicle_id,
            vehicle_name=name,
            entries=entries,
            total_quantity=quantity,
            total_cost=cost,
            total_co2_kg=co2,
            litres_per_100km=consumption,
        )
        for vehicle_id, name, entries, quantity, cost, co2, consumption in rows
    ]


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------

def _document_out(document) -> ComplianceDocumentOut:
    out = ComplianceDocumentOut.model_validate(document)
    out.days_until_expiry = compliance_service.days_until_expiry(document)
    return out


@router.get(
    "/compliance/documents",
    response_model=Page[ComplianceDocumentOut],
    summary="Compliance documents",
)
async def list_documents(
    vehicle_id: uuid.UUID | None = Query(default=None),
    driver_id: uuid.UUID | None = Query(default=None),
    expiring_within_days: int | None = Query(default=None, ge=0, le=3650),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Page[ComplianceDocumentOut]:
    items, total = await compliance_service.list_documents(
        db,
        scope,
        vehicle_id=vehicle_id,
        driver_id=driver_id,
        expiring_within_days=expiring_within_days,
        limit=limit,
        offset=offset,
    )
    return Page[ComplianceDocumentOut](
        items=[_document_out(d) for d in items], total=total, limit=limit, offset=offset
    )


@router.post(
    "/compliance/documents",
    response_model=ComplianceDocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a compliance document",
)
async def create_document(
    payload: ComplianceDocumentCreate,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> ComplianceDocumentOut:
    document = await compliance_service.create_document(
        db, scope, data=payload.model_dump(), principal=principal, request=request
    )
    return _document_out(document)


@router.patch(
    "/compliance/documents/{document_id}",
    response_model=ComplianceDocumentOut,
    summary="Update a compliance document",
)
async def update_document(
    document_id: uuid.UUID,
    payload: ComplianceDocumentUpdate,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> ComplianceDocumentOut:
    document = await compliance_service.update_document(
        db,
        scope,
        document_id=document_id,
        data=payload.model_dump(exclude_unset=True),
        principal=principal,
        request=request,
    )
    return _document_out(document)


@router.delete(
    "/compliance/documents/{document_id}",
    response_model=Message,
    summary="Delete a compliance document",
)
async def delete_document(
    document_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Message:
    title = await compliance_service.delete_document(
        db, scope, document_id=document_id, principal=principal, request=request
    )
    return Message(detail=f"Document '{title}' deleted")
