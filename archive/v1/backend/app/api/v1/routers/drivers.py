"""Driver management API (customer-facing, tenant-scoped)."""

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
from app.models.enums import EmploymentStatus
from app.schemas.common import Page
from app.schemas.driver import (
    DriverCreate,
    DriverCreateResponse,
    DriverOut,
    DriverUpdate,
)
from app.services import drivers as driver_service

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.get("", response_model=Page[DriverOut], summary="List drivers")
async def list_drivers(
    employment_status: EmploymentStatus | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Page[DriverOut]:
    items, total = await driver_service.list_drivers(
        db,
        scope,
        employment_status=employment_status,
        search=search,
        limit=limit,
        offset=offset,
    )
    return Page[DriverOut](
        items=[DriverOut.model_validate(d) for d in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=DriverCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a driver profile (optionally with a mobile-app login)",
)
async def create_driver(
    payload: DriverCreate,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> DriverCreateResponse:
    data = payload.model_dump(exclude={"login_email"})
    driver, activation_url = await driver_service.create_driver(
        db,
        scope,
        data=data,
        login_email=payload.login_email,
        principal=principal,
        request=request,
    )
    return DriverCreateResponse(
        driver=DriverOut.model_validate(driver), activation_url=activation_url
    )


@router.get("/{driver_id}", response_model=DriverOut, summary="Get one driver")
async def get_driver(
    driver_id: uuid.UUID,
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> DriverOut:
    return DriverOut.model_validate(await driver_service.get_driver(db, scope, driver_id))


@router.patch("/{driver_id}", response_model=DriverOut, summary="Update a driver")
async def update_driver(
    driver_id: uuid.UUID,
    payload: DriverUpdate,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> DriverOut:
    driver = await driver_service.update_driver(
        db,
        scope,
        driver_id=driver_id,
        data=payload.model_dump(exclude_unset=True),
        principal=principal,
        request=request,
    )
    return DriverOut.model_validate(driver)


@router.delete(
    "/{driver_id}", response_model=DriverOut, summary="Mark a driver as terminated"
)
async def deactivate_driver(
    driver_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> DriverOut:
    driver = await driver_service.deactivate_driver(
        db, scope, driver_id=driver_id, principal=principal, request=request
    )
    return DriverOut.model_validate(driver)
