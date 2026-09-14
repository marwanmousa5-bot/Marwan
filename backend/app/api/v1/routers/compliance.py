"""Compliance & Documents - expiry workspace."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_or_404, paginate
from app.auth.deps import Principal, require_operator, require_tenant
from app.core.enums import DocumentStatus, DocumentType, Severity
from app.db.base import get_session
from app.models import Document, Driver, Vehicle
from app.schemas.common import Message
from app.services import alerts as alert_svc, audit
from app.services.derive import document_status

router = APIRouter()


class DocumentIn(BaseModel):
    type: DocumentType
    name: str = Field(min_length=1, max_length=200)
    vehicle_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    issuer: str | None = None
    reference: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    cost: float | None = None
    notes: str | None = None
    attachment: str | None = None


@router.get("/summary")
async def summary(principal: Principal = Depends(require_tenant),
                  session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    today = date.today()
    docs = (await session.execute(
        select(Document).where(Document.organization_id == org_id))).scalars().all()
    drivers = (await session.execute(
        select(Driver).where(Driver.organization_id == org_id))).scalars().all()

    counts = {DocumentStatus.VALID: 0, DocumentStatus.EXPIRING_SOON: 0,
              DocumentStatus.EXPIRED: 0}
    horizon = {7: 0, 14: 0, 30: 0, 90: 0}
    for d in docs:
        st = document_status(d.expiry_date, today=today)
        counts[st] = counts.get(st, 0) + 1
        if d.expiry_date:
            days = (d.expiry_date - today).days
            for h in horizon:
                if 0 <= days <= h:
                    horizon[h] += 1
    licences = {"valid": 0, "expiring_soon": 0, "expired": 0}
    for dr in drivers:
        licences[document_status(dr.license_expiry, today=today)] += 1

    return {
        "total": len(docs),
        "valid": counts.get(DocumentStatus.VALID, 0),
        "expiring_soon": counts.get(DocumentStatus.EXPIRING_SOON, 0),
        "expired": counts.get(DocumentStatus.EXPIRED, 0),
        "horizon": {f"within_{k}_days": v for k, v in horizon.items()},
        "driver_licences": licences,
        "compliance_rate": round(counts.get(DocumentStatus.VALID, 0) / len(docs) * 100, 1)
        if docs else 100.0,
    }


@router.get("")
async def list_documents(
    status_filter: str | None = Query(None, alias="status"),
    type_filter: str | None = Query(None, alias="type"),
    entity: str | None = Query(None, pattern="^(vehicle|driver|organization)$"),
    vehicle_id: uuid.UUID | None = None,
    driver_id: uuid.UUID | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1), size: int = Query(100, ge=1, le=300),
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
):
    org_id = principal.org_id
    stmt = select(Document).where(Document.organization_id == org_id)
    if type_filter:
        stmt = stmt.where(Document.type.in_(type_filter.split(",")))
    if entity:
        stmt = stmt.where(Document.entity_type == entity)
    if vehicle_id:
        stmt = stmt.where(Document.vehicle_id == vehicle_id)
    if driver_id:
        stmt = stmt.where(Document.driver_id == driver_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Document.name.ilike(like), Document.reference.ilike(like),
                              Document.issuer.ilike(like)))
    if status_filter:
        stmt = stmt.where(Document.status.in_(status_filter.split(",")))

    result = await paginate(session, stmt.order_by(Document.expiry_date.nullslast()),
                            page, size)
    vehicles = {v.id: v for v in (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id))).scalars().all()}
    drivers = {d.id: d for d in (await session.execute(
        select(Driver).where(Driver.organization_id == org_id))).scalars().all()}
    today = date.today()
    result["items"] = [{
        "id": str(d.id), "type": d.type, "name": d.name, "entity_type": d.entity_type,
        "issuer": d.issuer, "reference": d.reference,
        "issue_date": d.issue_date.isoformat() if d.issue_date else None,
        "expiry_date": d.expiry_date.isoformat() if d.expiry_date else None,
        "days_to_expiry": (d.expiry_date - today).days if d.expiry_date else None,
        "status": d.status, "cost": d.cost, "notes": d.notes,
        "has_attachment": bool(d.attachment),
        "vehicle": {"id": str(vehicles[d.vehicle_id].id),
                    "name": vehicles[d.vehicle_id].name,
                    "plate": vehicles[d.vehicle_id].plate}
        if d.vehicle_id in vehicles else None,
        "driver": {"id": str(drivers[d.driver_id].id),
                   "name": drivers[d.driver_id].full_name}
        if d.driver_id in drivers else None,
    } for d in result["items"]]
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_document(payload: DocumentIn,
                          principal: Principal = Depends(require_operator),
                          session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    if payload.vehicle_id:
        await get_or_404(session, Vehicle, payload.vehicle_id, org_id, "Vehicle")
        entity_type = "vehicle"
    elif payload.driver_id:
        await get_or_404(session, Driver, payload.driver_id, org_id, "Driver")
        entity_type = "driver"
    else:
        entity_type = "organization"
    cfg = principal.organization.settings or {}
    warn = max(cfg.get("document_alert_days", [30]))
    doc = Document(organization_id=org_id, entity_type=entity_type,
                   status=document_status(payload.expiry_date, warn_days=warn),
                   **payload.model_dump())
    session.add(doc)
    await session.flush()
    await audit.record(session, action="document.created", organization_id=org_id,
                       actor=principal.user, entity_type="document", entity_id=doc.id,
                       entity_label=doc.name, summary=f"Document added: {doc.name}")
    if doc.vehicle_id:
        await audit.timeline(session, organization_id=org_id, entity_type="vehicle",
                             entity_id=doc.vehicle_id, action="document_added",
                             actor=principal.user,
                             description=f"{doc.type.replace('_', ' ').title()} added"
                                         + (f", expires {doc.expiry_date}"
                                            if doc.expiry_date else "") + ".")
    await session.commit()
    return {"id": str(doc.id), "status": doc.status}


class DocumentUpdate(BaseModel):
    name: str | None = None
    issuer: str | None = None
    reference: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    cost: float | None = None
    notes: str | None = None
    attachment: str | None = None


@router.patch("/{document_id}")
async def update_document(document_id: uuid.UUID, payload: DocumentUpdate,
                          principal: Principal = Depends(require_operator),
                          session: AsyncSession = Depends(get_session)):
    doc: Document = await get_or_404(session, Document, document_id, principal.org_id,
                                     "Document")
    before = audit.snapshot(doc, ["name", "expiry_date", "status"])
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(doc, k, v)
    cfg = principal.organization.settings or {}
    doc.status = document_status(doc.expiry_date,
                                 warn_days=max(cfg.get("document_alert_days", [30])))
    if "expiry_date" in changes:
        doc.last_alerted_days = None  # renewal re-arms the reminder ladder
    await audit.record(session, action="document.updated",
                       organization_id=principal.org_id, actor=principal.user,
                       entity_type="document", entity_id=doc.id, entity_label=doc.name,
                       before=before, after=audit.snapshot(doc, ["name", "expiry_date",
                                                                 "status"]),
                       summary=f"Document updated: {doc.name}")
    await session.commit()
    return {"id": str(doc.id), "status": doc.status}


@router.delete("/{document_id}", response_model=Message)
async def delete_document(document_id: uuid.UUID,
                          principal: Principal = Depends(require_operator),
                          session: AsyncSession = Depends(get_session)):
    doc: Document = await get_or_404(session, Document, document_id, principal.org_id,
                                     "Document")
    name = doc.name
    await session.delete(doc)
    await audit.record(session, action="document.deleted",
                       organization_id=principal.org_id, actor=principal.user,
                       entity_type="document", entity_id=document_id, entity_label=name,
                       summary=f"Document deleted: {name}")
    await session.commit()
    return Message(detail=f"“{name}” deleted.")


@router.post("/scan", response_model=dict)
async def scan(principal: Principal = Depends(require_operator),
               session: AsyncSession = Depends(get_session)):
    """Re-evaluate expiry status and raise the configured reminders."""
    org_id = principal.org_id
    cfg = principal.organization.settings or {}
    ladder = sorted(cfg.get("document_alert_days", [30, 14, 7, 1]), reverse=True)
    today = date.today()
    now = datetime.now(timezone.utc)

    docs = (await session.execute(
        select(Document).where(Document.organization_id == org_id,
                               Document.expiry_date.isnot(None)))).scalars().all()
    raised = 0
    for d in docs:
        d.status = document_status(d.expiry_date, today=today, warn_days=max(ladder))
        days = (d.expiry_date - today).days
        step = next((s for s in ladder if days <= s), None)
        if days < 0:
            if d.last_alerted_days != -1:
                d.last_alerted_days = -1
                await alert_svc.raise_alert(
                    session, org_id=org_id, code="document_expired",
                    severity=Severity.CRITICAL,
                    title=f"{d.name} has expired",
                    detail=f"Expired {abs(days)} day{'s' if abs(days) != 1 else ''} ago.",
                    vehicle_id=d.vehicle_id, driver_id=d.driver_id, document_id=d.id,
                    dedupe_extra=f"doc:{d.id}",
                    evidence={"expiry_date": d.expiry_date.isoformat(),
                              "days_overdue": abs(days)}, now=now)
                raised += 1
        elif step is not None and d.last_alerted_days != step:
            d.last_alerted_days = step
            await alert_svc.raise_alert(
                session, org_id=org_id, code="document_expiring",
                severity=Severity.HIGH if step <= 7 else Severity.MEDIUM,
                title=f"{d.name} expires in {days} day{'s' if days != 1 else ''}",
                detail=f"Renew before {d.expiry_date.isoformat()}.",
                vehicle_id=d.vehicle_id, driver_id=d.driver_id, document_id=d.id,
                dedupe_extra=f"doc:{d.id}:{step}",
                evidence={"expiry_date": d.expiry_date.isoformat(),
                          "days_remaining": days}, now=now)
            raised += 1

    # driver licences live on the driver record, not the document table
    drivers = (await session.execute(
        select(Driver).where(Driver.organization_id == org_id,
                             Driver.license_expiry.isnot(None)))).scalars().all()
    for dr in drivers:
        days = (dr.license_expiry - today).days
        if days <= max(ladder):
            await alert_svc.raise_alert(
                session, org_id=org_id, code="license_expiring",
                severity=Severity.CRITICAL if days < 0 else Severity.MEDIUM,
                title=f"{dr.full_name}'s licence "
                      + ("has expired" if days < 0 else f"expires in {days} days"),
                detail=f"Licence {dr.license_number or ''} expires "
                       f"{dr.license_expiry.isoformat()}.".strip(),
                driver_id=dr.id, dedupe_extra=f"licence:{dr.id}",
                evidence={"expiry": dr.license_expiry.isoformat(), "days": days},
                now=now)
            raised += 1

    await session.commit()
    return {"documents_checked": len(docs), "drivers_checked": len(drivers),
            "alerts_raised": raised}
