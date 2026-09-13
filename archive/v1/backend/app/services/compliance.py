"""Compliance documents with expiry tracking (Section 4 item 9)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal
from app.core.errors import NotFoundError, ValidationError
from app.core.tenancy import TenantScope
from app.models.compliance import ComplianceDocument
from app.models.driver import Driver
from app.models.enums import AuditAction
from app.models.vehicle import Vehicle
from app.services import audit


def today() -> date:
    return datetime.now(UTC).date()


def days_until_expiry(document: ComplianceDocument) -> int | None:
    if document.expires_on is None:
        return None
    return (document.expires_on - today()).days


async def list_documents(
    db: AsyncSession,
    scope: TenantScope,
    *,
    vehicle_id: uuid.UUID | None = None,
    driver_id: uuid.UUID | None = None,
    expiring_within_days: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ComplianceDocument], int]:
    stmt = scope.select(ComplianceDocument)
    if vehicle_id is not None:
        stmt = stmt.where(ComplianceDocument.vehicle_id == vehicle_id)
    if driver_id is not None:
        stmt = stmt.where(ComplianceDocument.driver_id == driver_id)
    if expiring_within_days is not None:
        from datetime import timedelta

        stmt = stmt.where(
            ComplianceDocument.expires_on.is_not(None),
            ComplianceDocument.expires_on
            <= today() + timedelta(days=expiring_within_days),
        )

    total = int(
        (await db.execute(sa.select(sa.func.count()).select_from(stmt.subquery())))
        .scalar_one()
    )
    result = await db.execute(
        stmt.order_by(ComplianceDocument.expires_on.asc().nullslast())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def create_document(
    db: AsyncSession,
    scope: TenantScope,
    *,
    data: dict,
    principal: Principal | None = None,
    request: Request | None = None,
) -> ComplianceDocument:
    vehicle_id = data.get("vehicle_id")
    driver_id = data.get("driver_id")
    if not vehicle_id and not driver_id:
        raise ValidationError("A document must be attached to a vehicle or a driver")
    if vehicle_id and await scope.get(db, Vehicle, vehicle_id) is None:
        raise NotFoundError("Vehicle not found")
    if driver_id and await scope.get(db, Driver, driver_id) is None:
        raise NotFoundError("Driver not found")

    document = ComplianceDocument(
        **data, uploaded_by_user_id=principal.user_id if principal else None
    )
    scope.assign(document)
    db.add(document)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="compliance_document",
        entity_id=document.id,
        summary=f"Document '{document.title}' added (expires {document.expires_on})",
        request=request,
    )
    return document


async def update_document(
    db: AsyncSession,
    scope: TenantScope,
    *,
    document_id: uuid.UUID,
    data: dict,
    principal: Principal | None = None,
    request: Request | None = None,
) -> ComplianceDocument:
    document = await scope.get_or_404(
        db, ComplianceDocument, document_id, label="Document"
    )
    fields = ["title", "reference_number", "issuer", "issued_on", "expires_on", "cost"]
    before = audit.snapshot(document, fields)

    for key, value in data.items():
        setattr(document, key, value)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="compliance_document",
        entity_id=document.id,
        summary=f"Document '{document.title}' updated",
        changes=audit.diff(before, audit.snapshot(document, fields)),
        request=request,
    )
    return document


async def delete_document(
    db: AsyncSession,
    scope: TenantScope,
    *,
    document_id: uuid.UUID,
    principal: Principal | None = None,
    request: Request | None = None,
) -> str:
    document = await scope.get_or_404(
        db, ComplianceDocument, document_id, label="Document"
    )
    title = document.title
    await db.delete(document)
    await audit.record(
        db,
        action=AuditAction.DELETE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="compliance_document",
        entity_id=document_id,
        summary=f"Document '{title}' deleted",
        request=request,
    )
    return title
