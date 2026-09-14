"""Maintenance Operations Centre: dashboard, schedules, work orders, calendar."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_or_404, paginate
from app.auth.deps import Principal, require_admin_of_org, require_operator, require_tenant
from app.core.enums import (CostCategory, MaintenanceCategory, MaintenanceStatus,
                            OPEN_WORK_ORDER_STATUSES, Priority, VehicleLifecycle,
                            WorkOrderStatus)
from app.db.base import get_session
from app.models import (Alert, CostRecord, MaintenanceRecord, MaintenanceSchedule,
                        MaintenanceTemplate, TimelineEvent, Vehicle, WorkOrder,
                        WorkOrderPart, Workshop)
from app.schemas.common import Message
from app.services import alerts as alert_svc, audit, maintenance as maint_svc
from app.websocket import events as ev
from app.websocket.events import bus

router = APIRouter()

WO_FLOW = {
    WorkOrderStatus.REQUESTED: {WorkOrderStatus.APPROVED, WorkOrderStatus.CANCELLED},
    WorkOrderStatus.APPROVED: {WorkOrderStatus.SCHEDULED, WorkOrderStatus.CANCELLED},
    WorkOrderStatus.SCHEDULED: {WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.CANCELLED},
    WorkOrderStatus.IN_PROGRESS: {WorkOrderStatus.WAITING_FOR_PARTS,
                                  WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED},
    WorkOrderStatus.WAITING_FOR_PARTS: {WorkOrderStatus.IN_PROGRESS,
                                        WorkOrderStatus.CANCELLED},
    WorkOrderStatus.COMPLETED: set(),
    WorkOrderStatus.CANCELLED: set(),
}


@router.get("/summary")
async def summary(principal: Principal = Depends(require_tenant),
                  session: AsyncSession = Depends(get_session)):
    """Every number here is a filter the UI can jump to (spec 7.1)."""
    org_id = principal.org_id
    today = date.today()
    rows = (await session.execute(
        select(MaintenanceSchedule.status, func.count()).where(
            MaintenanceSchedule.organization_id == org_id,
            MaintenanceSchedule.is_active.is_(True)).group_by(MaintenanceSchedule.status)
    )).all()
    counts = {s: n for s, n in rows}

    due_today = (await session.execute(
        select(func.count()).select_from(MaintenanceSchedule).where(
            MaintenanceSchedule.organization_id == org_id,
            MaintenanceSchedule.is_active.is_(True),
            MaintenanceSchedule.due_at_date == today))).scalar_one()
    due_week = (await session.execute(
        select(func.count()).select_from(MaintenanceSchedule).where(
            MaintenanceSchedule.organization_id == org_id,
            MaintenanceSchedule.is_active.is_(True),
            MaintenanceSchedule.due_at_date > today,
            MaintenanceSchedule.due_at_date <= today + timedelta(days=7)))).scalar_one()
    due_month = (await session.execute(
        select(func.count()).select_from(MaintenanceSchedule).where(
            MaintenanceSchedule.organization_id == org_id,
            MaintenanceSchedule.is_active.is_(True),
            MaintenanceSchedule.due_at_date > today,
            MaintenanceSchedule.due_at_date <= today + timedelta(days=30)))).scalar_one()
    open_wo = (await session.execute(
        select(func.count()).select_from(WorkOrder).where(
            WorkOrder.organization_id == org_id,
            WorkOrder.status.in_(OPEN_WORK_ORDER_STATUSES)))).scalar_one()
    in_workshop = (await session.execute(
        select(func.count(func.distinct(WorkOrder.vehicle_id))).where(
            WorkOrder.organization_id == org_id,
            WorkOrder.status.in_([WorkOrderStatus.IN_PROGRESS,
                                  WorkOrderStatus.WAITING_FOR_PARTS]))).scalar_one())
    estimated = (await session.execute(
        select(func.coalesce(func.sum(
            func.coalesce(WorkOrder.estimated_cost, 0.0)))).where(
            WorkOrder.organization_id == org_id,
            WorkOrder.status.in_(OPEN_WORK_ORDER_STATUSES)))).scalar_one()
    spend_30d = (await session.execute(
        select(func.coalesce(func.sum(MaintenanceRecord.total_cost), 0.0)).where(
            MaintenanceRecord.organization_id == org_id,
            MaintenanceRecord.service_date >= today - timedelta(days=30)))).scalar_one()

    return {
        "overdue": counts.get(MaintenanceStatus.OVERDUE, 0),
        "critical": counts.get(MaintenanceStatus.CRITICAL, 0),
        "due": counts.get(MaintenanceStatus.DUE, 0),
        "due_soon": counts.get(MaintenanceStatus.DUE_SOON, 0),
        "healthy": counts.get(MaintenanceStatus.HEALTHY, 0),
        "due_today": due_today, "due_this_week": due_week, "due_this_month": due_month,
        "in_workshop": in_workshop, "open_work_orders": open_wo,
        "estimated_cost": round(float(estimated), 2),
        "spend_30d": round(float(spend_30d), 2),
    }


@router.get("/schedules")
async def list_schedules(
    status_filter: str | None = Query(None, alias="status"),
    vehicle_id: uuid.UUID | None = None,
    due: str | None = Query(None, pattern="^(today|week|month|overdue)$"),
    q: str | None = None,
    page: int = Query(1, ge=1), size: int = Query(100, ge=1, le=300),
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
):
    org_id = principal.org_id
    today = date.today()
    stmt = select(MaintenanceSchedule).where(
        MaintenanceSchedule.organization_id == org_id,
        MaintenanceSchedule.is_active.is_(True))
    if status_filter:
        stmt = stmt.where(MaintenanceSchedule.status.in_(status_filter.split(",")))
    if vehicle_id:
        stmt = stmt.where(MaintenanceSchedule.vehicle_id == vehicle_id)
    if due == "today":
        stmt = stmt.where(MaintenanceSchedule.due_at_date == today)
    elif due == "week":
        stmt = stmt.where(MaintenanceSchedule.due_at_date <= today + timedelta(days=7))
    elif due == "month":
        stmt = stmt.where(MaintenanceSchedule.due_at_date <= today + timedelta(days=30))
    elif due == "overdue":
        stmt = stmt.where(MaintenanceSchedule.status.in_(
            [MaintenanceStatus.OVERDUE, MaintenanceStatus.CRITICAL]))
    if q:
        stmt = stmt.where(MaintenanceSchedule.name.ilike(f"%{q.strip()}%"))

    result = await paginate(session, stmt.order_by(
        MaintenanceSchedule.due_at_date.nullslast()), page, size)
    vehicles = {v.id: v for v in (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id))).scalars().all()}
    wo_by_schedule = {w.schedule_id: w for w in (await session.execute(
        select(WorkOrder).where(WorkOrder.organization_id == org_id,
                                WorkOrder.status.in_(OPEN_WORK_ORDER_STATUSES),
                                WorkOrder.schedule_id.isnot(None)))).scalars().all()}

    items = []
    for s in result["items"]:
        v = vehicles.get(s.vehicle_id)
        odo = v.odometer_km if v else 0
        wo = wo_by_schedule.get(s.id)
        items.append({
            "id": str(s.id), "name": s.name, "category": s.category,
            "status": s.status, "priority": s.priority,
            "vehicle": {"id": str(v.id), "name": v.name, "plate": v.plate,
                        "odometer_km": round(odo, 1)} if v else None,
            "interval_km": s.interval_km, "interval_months": s.interval_months,
            "due_at_km": s.due_at_km,
            "due_at_date": s.due_at_date.isoformat() if s.due_at_date else None,
            "km_remaining": round(s.km_remaining(odo), 1) if s.due_at_km is not None else None,
            "days_remaining": s.days_remaining(today),
            "due_summary": maint_svc.describe_due(s, odo, today),
            "estimated_cost": s.estimated_cost,
            "estimated_minutes": s.estimated_minutes,
            "work_order": {"id": str(wo.id), "reference": wo.reference,
                           "status": wo.status} if wo else None,
        })
    result["items"] = items
    return result


class ScheduleIn(BaseModel):
    vehicle_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    category: MaintenanceCategory = MaintenanceCategory.GENERAL_INSPECTION
    interval_km: float | None = None
    interval_months: int | None = None
    last_service_km: float | None = None
    last_service_date: date | None = None
    priority: Priority = Priority.NORMAL
    estimated_cost: float = 0
    estimated_minutes: int = 120
    template_id: uuid.UUID | None = None


def _apply_due(schedule: MaintenanceSchedule, vehicle: Vehicle) -> None:
    base_km = schedule.last_service_km if schedule.last_service_km is not None \
        else vehicle.odometer_km
    if schedule.interval_km:
        schedule.due_at_km = round(base_km + schedule.interval_km, 1)
    base_date = schedule.last_service_date or date.today()
    if schedule.interval_months:
        schedule.due_at_date = base_date + timedelta(days=schedule.interval_months * 30)


@router.post("/schedules", status_code=status.HTTP_201_CREATED)
async def create_schedule(payload: ScheduleIn,
                          principal: Principal = Depends(require_operator),
                          session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    if not payload.interval_km and not payload.interval_months:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Set a mileage interval, a time interval, or both.")
    vehicle: Vehicle = await get_or_404(session, Vehicle, payload.vehicle_id, org_id,
                                        "Vehicle")
    schedule = MaintenanceSchedule(organization_id=org_id, **payload.model_dump())
    _apply_due(schedule, vehicle)
    session.add(schedule)
    await session.flush()
    await maint_svc.evaluate_vehicle(session, org_id=org_id, vehicle=vehicle,
                                     org_settings=principal.organization.settings)
    await audit.record(session, action="maintenance_schedule.created",
                       organization_id=org_id, actor=principal.user,
                       entity_type="maintenance_schedule", entity_id=schedule.id,
                       entity_label=schedule.name,
                       summary=f"{schedule.name} scheduled for {vehicle.name}")
    await audit.timeline(session, organization_id=org_id, entity_type="vehicle",
                         entity_id=vehicle.id, action="schedule_created",
                         actor=principal.user,
                         description=f"Preventive schedule added: {schedule.name}.")
    await session.commit()
    return {"id": str(schedule.id), "status": schedule.status,
            "due_at_km": schedule.due_at_km,
            "due_at_date": schedule.due_at_date.isoformat() if schedule.due_at_date else None}


@router.get("/calendar")
async def calendar(start: date, end: date,
                   principal: Principal = Depends(require_tenant),
                   session: AsyncSession = Depends(get_session)):
    """Scheduled services, work orders and workshop bookings in one feed."""
    org_id = principal.org_id
    if (end - start).days > 120:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Choose a range of 120 days or less.")
    vehicles = {v.id: v for v in (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id))).scalars().all()}
    schedules = (await session.execute(
        select(MaintenanceSchedule).where(
            MaintenanceSchedule.organization_id == org_id,
            MaintenanceSchedule.is_active.is_(True),
            MaintenanceSchedule.due_at_date.between(start, end)))).scalars().all()
    orders = (await session.execute(
        select(WorkOrder).where(
            WorkOrder.organization_id == org_id,
            WorkOrder.scheduled_start.isnot(None),
            func.date(WorkOrder.scheduled_start).between(start, end)))).scalars().all()
    workshops = {w.id: w for w in (await session.execute(
        select(Workshop).where(Workshop.organization_id == org_id))).scalars().all()}

    events = []
    for s in schedules:
        v = vehicles.get(s.vehicle_id)
        events.append({
            "kind": "schedule", "id": str(s.id), "date": s.due_at_date.isoformat(),
            "title": f"{s.name} — {v.name if v else 'Vehicle'}",
            "status": s.status, "priority": s.priority,
            "vehicle": {"id": str(v.id), "name": v.name} if v else None,
            "estimated_minutes": s.estimated_minutes,
        })
    for w in orders:
        v = vehicles.get(w.vehicle_id)
        shop = workshops.get(w.workshop_id)
        events.append({
            "kind": "work_order", "id": str(w.id),
            "date": w.scheduled_start.date().isoformat(),
            "start": w.scheduled_start.isoformat(),
            "end": w.expected_completion.isoformat() if w.expected_completion else None,
            "title": f"{w.reference} — {w.title}",
            "status": w.status, "priority": w.priority,
            "vehicle": {"id": str(v.id), "name": v.name} if v else None,
            "workshop": shop.name if shop else None,
        })
    events.sort(key=lambda e: e["date"])
    return {"start": start.isoformat(), "end": end.isoformat(), "events": events}


# --- work orders -----------------------------------------------------------
class PartIn(BaseModel):
    name: str
    sku: str | None = None
    quantity: float = 1
    unit_cost: float = 0
    supplier: str | None = None
    warranty_months: int | None = None


class WorkOrderIn(BaseModel):
    vehicle_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    category: MaintenanceCategory = MaintenanceCategory.GENERAL_INSPECTION
    priority: Priority = Priority.NORMAL
    problem: str | None = None
    schedule_id: uuid.UUID | None = None
    workshop_id: uuid.UUID | None = None
    technician: str | None = None
    scheduled_start: datetime | None = None
    expected_completion: datetime | None = None
    estimated_cost: float = 0
    labor_rate: float = 75
    incident_id: uuid.UUID | None = None
    acknowledge_conflict: bool = False


@router.post("/work-orders/impact")
async def work_order_impact(payload: WorkOrderIn,
                            principal: Principal = Depends(require_operator),
                            session: AsyncSession = Depends(get_session)):
    """What scheduling this work order would actually disrupt (spec 7.14)."""
    vehicle: Vehicle = await get_or_404(session, Vehicle, payload.vehicle_id,
                                        principal.org_id, "Vehicle")
    start = payload.scheduled_start or datetime.now(timezone.utc)
    minutes = 120
    if payload.expected_completion and payload.scheduled_start:
        minutes = max(30, round((payload.expected_completion
                                 - payload.scheduled_start).total_seconds() / 60))
    return await maint_svc.impact_analysis(session, org_id=principal.org_id,
                                           vehicle=vehicle, start=start,
                                           duration_minutes=minutes)


@router.post("/work-orders", status_code=status.HTTP_201_CREATED)
async def create_work_order(payload: WorkOrderIn,
                            principal: Principal = Depends(require_operator),
                            session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    vehicle: Vehicle = await get_or_404(session, Vehicle, payload.vehicle_id, org_id,
                                        "Vehicle")
    if payload.scheduled_start:
        minutes = 120
        if payload.expected_completion:
            minutes = max(30, round((payload.expected_completion
                                     - payload.scheduled_start).total_seconds() / 60))
        impact = await maint_svc.impact_analysis(session, org_id=org_id, vehicle=vehicle,
                                                 start=payload.scheduled_start,
                                                 duration_minutes=minutes)
        if impact["has_conflict"] and not payload.acknowledge_conflict:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "message": f"{vehicle.name} has {impact['affected_task_count']} task"
                               f"{'s' if impact['affected_task_count'] != 1 else ''} "
                               f"scheduled during that window.",
                    "impact": impact,
                },
            )

    count = (await session.execute(
        select(func.count()).select_from(WorkOrder).where(
            WorkOrder.organization_id == org_id))).scalar_one()
    data = payload.model_dump(exclude={"acknowledge_conflict"})
    wo = WorkOrder(organization_id=org_id, reference=maint_svc.next_reference("WO", count),
                   requested_by_id=principal.user.id, odometer_km=vehicle.odometer_km,
                   **data)
    session.add(wo)
    await session.flush()

    if wo.schedule_id:
        sched = await session.get(MaintenanceSchedule, wo.schedule_id)
        if sched:
            sched.status = MaintenanceStatus.IN_WORKSHOP

    await audit.record(session, action="work_order.created", organization_id=org_id,
                       actor=principal.user, entity_type="work_order", entity_id=wo.id,
                       entity_label=wo.reference,
                       summary=f"{wo.reference} raised for {vehicle.name}: {wo.title}")
    await audit.timeline(session, organization_id=org_id, entity_type="work_order",
                         entity_id=wo.id, action="requested", actor=principal.user,
                         description=f"Work order raised: {wo.title}.")
    await audit.timeline(session, organization_id=org_id, entity_type="vehicle",
                         entity_id=vehicle.id, action="work_order_created",
                         actor=principal.user,
                         description=f"Work order {wo.reference} raised: {wo.title}.",
                         related_type="work_order", related_id=wo.id)
    await bus.publish(org_id, ev.WORK_ORDER_CREATED,
                      {"id": str(wo.id), "reference": wo.reference,
                       "vehicle_id": str(vehicle.id)})
    await session.commit()
    return {"id": str(wo.id), "reference": wo.reference, "status": wo.status}


@router.get("/work-orders")
async def list_work_orders(
    status_filter: str | None = Query(None, alias="status"),
    vehicle_id: uuid.UUID | None = None,
    workshop_id: uuid.UUID | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
):
    org_id = principal.org_id
    stmt = select(WorkOrder).where(WorkOrder.organization_id == org_id)
    if status_filter:
        stmt = stmt.where(WorkOrder.status.in_(status_filter.split(",")))
    if vehicle_id:
        stmt = stmt.where(WorkOrder.vehicle_id == vehicle_id)
    if workshop_id:
        stmt = stmt.where(WorkOrder.workshop_id == workshop_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(WorkOrder.reference.ilike(like), WorkOrder.title.ilike(like)))
    result = await paginate(session, stmt.order_by(WorkOrder.created_at.desc()), page, size)
    vehicles = {v.id: v for v in (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id))).scalars().all()}
    workshops = {w.id: w for w in (await session.execute(
        select(Workshop).where(Workshop.organization_id == org_id))).scalars().all()}
    now = datetime.now(timezone.utc)
    result["items"] = [{
        "id": str(w.id), "reference": w.reference, "title": w.title,
        "status": w.status, "priority": w.priority, "category": w.category,
        "vehicle": {"id": str(vehicles[w.vehicle_id].id),
                    "name": vehicles[w.vehicle_id].name,
                    "plate": vehicles[w.vehicle_id].plate}
        if w.vehicle_id in vehicles else None,
        "workshop": workshops[w.workshop_id].name if w.workshop_id in workshops else None,
        "technician": w.technician,
        "scheduled_start": w.scheduled_start.isoformat() if w.scheduled_start else None,
        "expected_completion": w.expected_completion.isoformat()
        if w.expected_completion else None,
        "total_cost": w.total_cost, "estimated_cost": w.estimated_cost,
        "is_overdue": bool(w.expected_completion and w.status in OPEN_WORK_ORDER_STATUSES
                           and w.expected_completion < now),
        "created_at": w.created_at.isoformat(),
    } for w in result["items"]]
    return result


@router.get("/work-orders/{wo_id}")
async def work_order_detail(wo_id: uuid.UUID,
                            principal: Principal = Depends(require_tenant),
                            session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    wo: WorkOrder = await get_or_404(session, WorkOrder, wo_id, org_id, "Work order")
    vehicle = await session.get(Vehicle, wo.vehicle_id)
    workshop = await session.get(Workshop, wo.workshop_id) if wo.workshop_id else None
    timeline = (await session.execute(
        select(TimelineEvent).where(TimelineEvent.entity_type == "work_order",
                                    TimelineEvent.entity_id == wo.id)
        .order_by(TimelineEvent.occurred_at))).scalars().all()
    return {
        "id": str(wo.id), "reference": wo.reference, "title": wo.title,
        "status": wo.status, "priority": wo.priority, "category": wo.category,
        "problem": wo.problem, "diagnosis": wo.diagnosis,
        "work_performed": wo.work_performed, "technician": wo.technician,
        "notes": wo.notes, "attachments": wo.attachments,
        "vehicle": {"id": str(vehicle.id), "name": vehicle.name, "plate": vehicle.plate,
                    "odometer_km": round(vehicle.odometer_km, 1)} if vehicle else None,
        "workshop": {"id": str(workshop.id), "name": workshop.name,
                     "address": workshop.address,
                     "contact_phone": workshop.contact_phone} if workshop else None,
        "scheduled_start": wo.scheduled_start.isoformat() if wo.scheduled_start else None,
        "expected_completion": wo.expected_completion.isoformat()
        if wo.expected_completion else None,
        "actual_start": wo.actual_start.isoformat() if wo.actual_start else None,
        "actual_completion": wo.actual_completion.isoformat()
        if wo.actual_completion else None,
        "downtime_hours": wo.downtime_hours,
        "labor_hours": wo.labor_hours, "labor_rate": wo.labor_rate,
        "labor_cost": wo.labor_cost, "parts_cost": wo.parts_cost,
        "total_cost": wo.total_cost, "estimated_cost": wo.estimated_cost,
        "odometer_km": wo.odometer_km,
        "parts": [{"id": str(p.id), "name": p.name, "sku": p.sku,
                   "quantity": p.quantity, "unit_cost": p.unit_cost,
                   "total": p.total, "supplier": p.supplier,
                   "warranty_months": p.warranty_months} for p in wo.parts],
        "timeline": [{"id": str(e.id), "occurred_at": e.occurred_at.isoformat(),
                      "actor_name": e.actor_name, "actor_type": e.actor_type,
                      "action": e.action, "description": e.description} for e in timeline],
        "allowed_transitions": sorted(WO_FLOW.get(wo.status, set())),
    }


class WorkOrderUpdate(BaseModel):
    title: str | None = None
    priority: Priority | None = None
    problem: str | None = None
    diagnosis: str | None = None
    work_performed: str | None = None
    technician: str | None = None
    workshop_id: uuid.UUID | None = None
    scheduled_start: datetime | None = None
    expected_completion: datetime | None = None
    labor_hours: float | None = None
    labor_rate: float | None = None
    notes: str | None = None


@router.patch("/work-orders/{wo_id}")
async def update_work_order(wo_id: uuid.UUID, payload: WorkOrderUpdate,
                            principal: Principal = Depends(require_operator),
                            session: AsyncSession = Depends(get_session)):
    wo: WorkOrder = await get_or_404(session, WorkOrder, wo_id, principal.org_id,
                                     "Work order")
    if wo.status in (WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"A {wo.status} work order can no longer be edited.")
    fields = ["title", "priority", "technician", "labor_hours", "scheduled_start"]
    before = audit.snapshot(wo, fields)
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(wo, k, v)
    await maint_svc.apply_work_order_costs(wo)
    await audit.record(session, action="work_order.updated",
                       organization_id=principal.org_id, actor=principal.user,
                       entity_type="work_order", entity_id=wo.id,
                       entity_label=wo.reference, before=before,
                       after=audit.snapshot(wo, fields),
                       summary=f"{wo.reference} updated")
    await audit.timeline(session, organization_id=principal.org_id,
                         entity_type="work_order", entity_id=wo.id, action="updated",
                         actor=principal.user,
                         description="Work order updated: " + ", ".join(
                             k.replace('_', ' ') for k in changes))
    await session.commit()
    return {"id": str(wo.id), "total_cost": wo.total_cost}


@router.post("/work-orders/{wo_id}/parts", status_code=status.HTTP_201_CREATED)
async def add_part(wo_id: uuid.UUID, payload: PartIn,
                   principal: Principal = Depends(require_operator),
                   session: AsyncSession = Depends(get_session)):
    wo: WorkOrder = await get_or_404(session, WorkOrder, wo_id, principal.org_id,
                                     "Work order")
    if wo.status in (WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Parts cannot be added to a closed work order.")
    part = WorkOrderPart(organization_id=principal.org_id, work_order_id=wo.id,
                         **payload.model_dump())
    session.add(part)
    await session.flush()
    await session.refresh(wo, ["parts"])
    await maint_svc.apply_work_order_costs(wo)
    await audit.timeline(session, organization_id=principal.org_id,
                         entity_type="work_order", entity_id=wo.id, action="part_added",
                         actor=principal.user,
                         description=f"Part added: {part.quantity:g} × {part.name} "
                                     f"(€{part.total:.2f}).")
    await session.commit()
    return {"id": str(part.id), "total": part.total, "parts_cost": wo.parts_cost,
            "total_cost": wo.total_cost}


@router.delete("/work-orders/{wo_id}/parts/{part_id}", response_model=Message)
async def remove_part(wo_id: uuid.UUID, part_id: uuid.UUID,
                      principal: Principal = Depends(require_operator),
                      session: AsyncSession = Depends(get_session)):
    wo: WorkOrder = await get_or_404(session, WorkOrder, wo_id, principal.org_id,
                                     "Work order")
    part = await session.get(WorkOrderPart, part_id)
    if part is None or part.work_order_id != wo.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Part not found on this work order.")
    name = part.name
    await session.delete(part)
    await session.flush()
    await session.refresh(wo, ["parts"])
    await maint_svc.apply_work_order_costs(wo)
    await session.commit()
    return Message(detail=f"{name} removed.")


class WOStatusIn(BaseModel):
    status: WorkOrderStatus
    note: str | None = None


@router.post("/work-orders/{wo_id}/status")
async def set_wo_status(wo_id: uuid.UUID, payload: WOStatusIn,
                        principal: Principal = Depends(require_operator),
                        session: AsyncSession = Depends(get_session)):
    """Drives the work-order lifecycle and everything that depends on it."""
    org_id = principal.org_id
    wo: WorkOrder = await get_or_404(session, WorkOrder, wo_id, org_id, "Work order")
    target = payload.status
    if target not in WO_FLOW.get(wo.status, set()):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A {wo.status.replace('_', ' ')} work order cannot move to "
            f"{target.replace('_', ' ')}.",
        )
    now = datetime.now(timezone.utc)
    previous = wo.status
    wo.status = target
    vehicle = await session.get(Vehicle, wo.vehicle_id)

    if target == WorkOrderStatus.IN_PROGRESS:
        wo.actual_start = wo.actual_start or now
        if vehicle:
            vehicle.lifecycle = VehicleLifecycle.MAINTENANCE
    elif target == WorkOrderStatus.COMPLETED:
        wo.actual_completion = now
        if wo.actual_start:
            wo.downtime_hours = round((now - wo.actual_start).total_seconds() / 3600, 2)
        await maint_svc.apply_work_order_costs(wo)
        if vehicle:
            vehicle.lifecycle = VehicleLifecycle.ACTIVE
            session.add(MaintenanceRecord(
                organization_id=org_id, vehicle_id=vehicle.id, work_order_id=wo.id,
                schedule_id=wo.schedule_id, category=wo.category,
                service_date=now.date(), odometer_km=vehicle.odometer_km,
                work_performed=wo.work_performed or wo.title,
                parts_cost=wo.parts_cost, labor_cost=wo.labor_cost,
                total_cost=wo.total_cost, downtime_hours=wo.downtime_hours or 0,
                technician=wo.technician,
            ))
            if wo.total_cost:
                session.add(CostRecord(
                    organization_id=org_id, vehicle_id=vehicle.id,
                    category=CostCategory.MAINTENANCE, incurred_on=now.date(),
                    amount=wo.total_cost, description=f"{wo.reference}: {wo.title}",
                    source_type="work_order", source_id=wo.id,
                    odometer_km=vehicle.odometer_km,
                ))
            # reset the preventive schedule from this service point
            if wo.schedule_id:
                sched = await session.get(MaintenanceSchedule, wo.schedule_id)
                if sched:
                    sched.last_service_km = vehicle.odometer_km
                    sched.last_service_date = now.date()
                    sched.last_alerted_status = None
                    if sched.interval_km:
                        sched.due_at_km = round(vehicle.odometer_km + sched.interval_km, 1)
                    if sched.interval_months:
                        sched.due_at_date = now.date() + timedelta(
                            days=sched.interval_months * 30)
                    sched.status = MaintenanceStatus.HEALTHY
            # close the maintenance alerts this work order answers
            open_alerts = (await session.execute(
                select(Alert).where(
                    Alert.organization_id == org_id, Alert.vehicle_id == vehicle.id,
                    Alert.category == "maintenance",
                    Alert.status.in_(("triggered", "acknowledged", "investigating",
                                      "escalated")))
            )).scalars().all()
            for a in open_alerts:
                a.status = "resolved"
                a.resolved_at = now
                a.resolved_by_id = principal.user.id
                a.resolution_note = f"Resolved by {wo.reference}."
                await audit.timeline(session, organization_id=org_id, entity_type="alert",
                                     entity_id=a.id, action="resolved",
                                     actor=principal.user,
                                     description=f"Closed automatically by {wo.reference}.")
            await maint_svc.evaluate_vehicle(session, org_id=org_id, vehicle=vehicle,
                                             org_settings=principal.organization.settings,
                                             now=now)
    elif target == WorkOrderStatus.CANCELLED:
        wo.cancelled_reason = payload.note
        if wo.schedule_id:
            sched = await session.get(MaintenanceSchedule, wo.schedule_id)
            if sched and sched.status == MaintenanceStatus.IN_WORKSHOP:
                sched.status = MaintenanceStatus.DUE
        if vehicle and vehicle.lifecycle == VehicleLifecycle.MAINTENANCE:
            vehicle.lifecycle = VehicleLifecycle.ACTIVE

    await audit.record(session, action="work_order.status_changed", organization_id=org_id,
                       actor=principal.user, entity_type="work_order", entity_id=wo.id,
                       entity_label=wo.reference,
                       before={"status": previous}, after={"status": target},
                       summary=f"{wo.reference}: {previous} → {target}")
    await audit.timeline(session, organization_id=org_id, entity_type="work_order",
                         entity_id=wo.id, action=target, actor=principal.user,
                         occurred_at=now,
                         description=(payload.note or
                                      f"Status changed to {target.replace('_', ' ')}."))
    if vehicle:
        await audit.timeline(session, organization_id=org_id, entity_type="vehicle",
                             entity_id=vehicle.id, action=f"work_order_{target}",
                             actor=principal.user, occurred_at=now,
                             description=f"{wo.reference}: {target.replace('_', ' ')}.",
                             related_type="work_order", related_id=wo.id)
    await bus.publish(org_id, ev.WORK_ORDER_COMPLETED if target == WorkOrderStatus.COMPLETED
                      else ev.WORK_ORDER_UPDATED,
                      {"id": str(wo.id), "reference": wo.reference, "status": target,
                       "vehicle_id": str(wo.vehicle_id)})
    await session.commit()
    return {"id": str(wo.id), "status": wo.status, "total_cost": wo.total_cost,
            "downtime_hours": wo.downtime_hours}


@router.get("/vehicles/{vehicle_id}/history")
async def vehicle_history(vehicle_id: uuid.UUID,
                          principal: Principal = Depends(require_tenant),
                          session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    vehicle: Vehicle = await get_or_404(session, Vehicle, vehicle_id, org_id, "Vehicle")
    records = (await session.execute(
        select(MaintenanceRecord).where(MaintenanceRecord.vehicle_id == vehicle_id)
        .order_by(MaintenanceRecord.service_date.desc()))).scalars().all()
    health = await maint_svc.vehicle_health(session, vehicle,
                                            principal.organization.settings)
    total = sum(r.total_cost for r in records)
    downtime = sum(r.downtime_hours for r in records)
    span_km = max(1.0, vehicle.odometer_km - min((r.odometer_km for r in records),
                                                 default=vehicle.odometer_km))
    insight = None
    if health["repeat_categories"]:
        top = max(health["repeat_categories"], key=lambda r: r["count"])
        insight = {
            "label": "Fleet Intelligence",
            "text": f"{vehicle.name} has needed {top['category'].replace('_', ' ')} "
                    f"work {top['count']} times in the last six months. Inspect that "
                    f"system before the next scheduled service.",
        }
    return {
        "vehicle": {"id": str(vehicle.id), "name": vehicle.name, "plate": vehicle.plate,
                    "odometer_km": round(vehicle.odometer_km, 1)},
        "health": health,
        "records": [{"id": str(r.id), "service_date": r.service_date.isoformat(),
                     "category": r.category, "odometer_km": r.odometer_km,
                     "work_performed": r.work_performed, "parts_cost": r.parts_cost,
                     "labor_cost": r.labor_cost, "total_cost": r.total_cost,
                     "downtime_hours": r.downtime_hours, "workshop": r.workshop_name,
                     "technician": r.technician} for r in records],
        "totals": {
            "services": len(records),
            "total_cost": round(total, 2),
            "cost_per_service": round(total / len(records), 2) if records else 0,
            "cost_per_km": round(total / span_km, 3),
            "downtime_hours": round(downtime, 1),
            "failure_frequency_per_10000km": round(len(records) / span_km * 10000, 2)
            if span_km > 100 else 0,
        },
        "insight": insight,
    }


# --- workshops & templates --------------------------------------------------
@router.get("/workshops")
async def list_workshops(principal: Principal = Depends(require_tenant),
                         session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(Workshop).where(Workshop.organization_id == principal.org_id)
        .order_by(Workshop.name))).scalars().all()
    today = date.today()
    out = []
    for w in rows:
        booked = (await session.execute(
            select(func.count()).select_from(WorkOrder).where(
                WorkOrder.workshop_id == w.id,
                func.date(WorkOrder.scheduled_start) == today,
                WorkOrder.status.in_(OPEN_WORK_ORDER_STATUSES)))).scalar_one()
        out.append({"id": str(w.id), "name": w.name, "address": w.address,
                    "lat": w.lat, "lon": w.lon, "contact_name": w.contact_name,
                    "contact_phone": w.contact_phone, "services": w.services,
                    "daily_capacity": w.daily_capacity, "booked_today": booked,
                    "available_today": max(0, w.daily_capacity - booked),
                    "opening_time": w.opening_time, "closing_time": w.closing_time,
                    "is_internal": w.is_internal, "is_active": w.is_active})
    return out


@router.get("/templates")
async def list_templates(principal: Principal = Depends(require_tenant),
                         session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(MaintenanceTemplate).where(
            MaintenanceTemplate.organization_id == principal.org_id,
            MaintenanceTemplate.is_active.is_(True)).order_by(MaintenanceTemplate.name)
    )).scalars().all()
    return [{"id": str(t.id), "name": t.name, "description": t.description,
             "vehicle_types": t.vehicle_types, "items": t.items,
             "interval_km": t.interval_km, "interval_months": t.interval_months,
             "estimated_cost": t.estimated_cost,
             "estimated_minutes": t.estimated_minutes} for t in rows]


class ApplyTemplateIn(BaseModel):
    template_id: uuid.UUID
    vehicle_ids: list[uuid.UUID] = Field(min_length=1)


@router.post("/templates/apply")
async def apply_template(payload: ApplyTemplateIn,
                         principal: Principal = Depends(require_operator),
                         session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    template: MaintenanceTemplate = await get_or_404(session, MaintenanceTemplate,
                                                     payload.template_id, org_id,
                                                     "Template")
    created = 0
    for vid in payload.vehicle_ids:
        vehicle = await get_or_404(session, Vehicle, vid, org_id, "Vehicle")
        for item in template.items:
            schedule = MaintenanceSchedule(
                organization_id=org_id, vehicle_id=vehicle.id, template_id=template.id,
                name=item.get("label", template.name),
                category=item.get("category", "general_inspection"),
                interval_km=template.interval_km, interval_months=template.interval_months,
                last_service_km=vehicle.odometer_km, last_service_date=date.today(),
                estimated_cost=item.get("estimated_cost", 0),
                estimated_minutes=item.get("estimated_minutes", 60),
            )
            _apply_due(schedule, vehicle)
            session.add(schedule)
            created += 1
        await audit.timeline(session, organization_id=org_id, entity_type="vehicle",
                             entity_id=vehicle.id, action="template_applied",
                             actor=principal.user,
                             description=f"Applied maintenance template “{template.name}”.")
    await audit.record(session, action="maintenance_template.applied",
                       organization_id=org_id, actor=principal.user,
                       entity_type="maintenance_template", entity_id=template.id,
                       entity_label=template.name,
                       summary=f"{template.name} applied to "
                               f"{len(payload.vehicle_ids)} vehicles")
    await session.commit()
    return {"schedules_created": created, "vehicles": len(payload.vehicle_ids)}
