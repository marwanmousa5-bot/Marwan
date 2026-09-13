"""Driver management service."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal
from app.core.errors import NotFoundError
from app.core.tenancy import TenantScope
from app.models.driver import Driver
from app.models.enums import AuditAction, EmploymentStatus, UserRole
from app.models.organization import OrganizationSettings
from app.models.vehicle import Vehicle
from app.services import audit
from app.services.users import invite_user

AUDITED_FIELDS = [
    "full_name",
    "employee_number",
    "phone",
    "license_number",
    "license_class",
    "license_expiry",
    "employment_status",
    "assigned_vehicle_id",
]


async def list_drivers(
    db: AsyncSession,
    scope: TenantScope,
    *,
    employment_status: EmploymentStatus | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Driver], int]:
    stmt = scope.select(Driver)
    if employment_status is not None:
        stmt = stmt.where(Driver.employment_status == employment_status)
    if search:
        pattern = f"%{search.strip().lower()}%"
        stmt = stmt.where(sa.func.lower(Driver.full_name).like(pattern))

    total_result = await db.execute(
        sa.select(sa.func.count()).select_from(stmt.subquery())
    )
    result = await db.execute(stmt.order_by(Driver.full_name).limit(limit).offset(offset))
    return list(result.scalars().unique().all()), int(total_result.scalar_one())


async def get_driver(db: AsyncSession, scope: TenantScope, driver_id: uuid.UUID) -> Driver:
    return await scope.get_or_404(db, Driver, driver_id, label="Driver")


async def create_driver(
    db: AsyncSession,
    scope: TenantScope,
    *,
    data: dict,
    login_email: str | None = None,
    principal: Principal | None = None,
    request: Request | None = None,
) -> tuple[Driver, str | None]:
    if data.get("assigned_vehicle_id"):
        await _assert_vehicle_in_scope(db, scope, data["assigned_vehicle_id"])

    settings_row = await _org_settings(db, scope)
    driver = Driver(
        **data,
        points_balance=settings_row.driver_points_baseline if settings_row else 100,
    )
    scope.assign(driver)
    db.add(driver)
    await db.flush()

    activation_url: str | None = None
    if login_email:
        user, activation_url = await invite_user(
            db,
            scope,
            email=login_email,
            full_name=driver.full_name,
            role=UserRole.DRIVER,
            phone=driver.phone,
            create_driver_profile=False,
            principal=principal,
            request=request,
        )
        driver.user_id = user.id
        await db.flush()

    await audit.record(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="driver",
        entity_id=driver.id,
        summary=f"Driver '{driver.full_name}' created",
        changes={"after": audit.snapshot(driver, AUDITED_FIELDS)},
        request=request,
    )
    return driver, activation_url


async def update_driver(
    db: AsyncSession,
    scope: TenantScope,
    *,
    driver_id: uuid.UUID,
    data: dict,
    principal: Principal | None = None,
    request: Request | None = None,
) -> Driver:
    driver = await get_driver(db, scope, driver_id)
    before = audit.snapshot(driver, AUDITED_FIELDS)

    if data.get("assigned_vehicle_id"):
        await _assert_vehicle_in_scope(db, scope, data["assigned_vehicle_id"])

    for key, value in data.items():
        setattr(driver, key, value)
    await db.flush()

    changes = audit.diff(before, audit.snapshot(driver, AUDITED_FIELDS))
    if changes:
        await audit.record(
            db,
            action=AuditAction.UPDATE,
            principal=principal,
            organization_id=scope.organization_id,
            entity_type="driver",
            entity_id=driver.id,
            summary=f"Driver '{driver.full_name}' updated",
            changes=changes,
            request=request,
        )
    return driver


async def deactivate_driver(
    db: AsyncSession,
    scope: TenantScope,
    *,
    driver_id: uuid.UUID,
    principal: Principal | None = None,
    request: Request | None = None,
) -> Driver:
    driver = await get_driver(db, scope, driver_id)
    driver.employment_status = EmploymentStatus.TERMINATED
    driver.assigned_vehicle_id = None
    await audit.record(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="driver",
        entity_id=driver.id,
        summary=f"Driver '{driver.full_name}' marked as terminated",
        request=request,
    )
    return driver


async def _assert_vehicle_in_scope(
    db: AsyncSession, scope: TenantScope, vehicle_id: uuid.UUID
) -> None:
    if await scope.get(db, Vehicle, vehicle_id) is None:
        raise NotFoundError("Vehicle not found")


async def _org_settings(
    db: AsyncSession, scope: TenantScope
) -> OrganizationSettings | None:
    result = await db.execute(
        sa.select(OrganizationSettings)
        .where(OrganizationSettings.organization_id == scope.organization_id)
        .limit(1)
    )
    return result.scalar_one_or_none()
