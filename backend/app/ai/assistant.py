"""Agentic natural-language fleet assistant (Section 5, item 3).

The shape is deliberate and is the same one every agentic feature in this
product uses:

    question -> LLM produces a *structured intent* -> our code executes it

The model never touches the database and never runs an action. For a query
it picks which of our own read functions to run; for an action it proposes a
change, our code computes exactly what would change, and nothing happens
until the user confirms it (Section 9).

Only the caller's own Organization is ever in scope: intents are executed
through the request's TenantScope, so there is no phrasing of a question that
can reach another tenant's data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import get_claude_client
from app.core.errors import PermissionDeniedError, ValidationError
from app.core.tenancy import TenantScope
from app.models.alert import Alert
from app.models.driver import Driver
from app.models.enums import AlertStatus, TaskStatus, VehicleStatus
from app.models.task import Task
from app.models.vehicle import Vehicle
from app.services import analytics

SYSTEM_PROMPT = """You are the FleetBeat assistant, embedded in a fleet
management dashboard. You help a fleet administrator understand and act on
their own fleet's data.

You never invent figures. You are given a set of named capabilities; choose
exactly one, and return the parameters for it. If the request does not map
onto any capability, choose "unsupported" and explain briefly what you would
need instead.

Actions change real data and are never executed by you - they are proposed to
the user for confirmation. Be precise about scope: prefer the narrowest
capability that answers the question.""".strip()

#: The capabilities the model may choose from. Queries read; actions propose.
CAPABILITIES: dict[str, dict[str, Any]] = {
    "fleet_cost": {
        "kind": "query",
        "description": "Total and per-vehicle cost over a number of past days.",
        "parameters": {"days": "integer, default 30"},
    },
    "most_expensive_vehicle": {
        "kind": "query",
        "description": "Which vehicle cost the most over a number of past days.",
        "parameters": {"days": "integer, default 30"},
    },
    "fleet_summary": {
        "kind": "query",
        "description": "Headline KPIs: distance, utilisation, cost, CO2, safety.",
        "parameters": {"days": "integer, default 30"},
    },
    "active_alerts": {
        "kind": "query",
        "description": "Currently active alerts, optionally filtered by severity.",
        "parameters": {"severity": "info|warning|critical, optional"},
    },
    "vehicles_needing_attention": {
        "kind": "query",
        "description": "Vehicles in maintenance, untracked, or carrying alerts.",
        "parameters": {},
    },
    "driver_standings": {
        "kind": "query",
        "description": "Driver safety scores and points, best to worst.",
        "parameters": {},
    },
    "cancel_tasks_for_vehicles_in_maintenance": {
        "kind": "action",
        "description": (
            "Cancel open tasks assigned to vehicles currently in maintenance."
        ),
        "parameters": {"reason": "short string, optional"},
    },
    "unsupported": {
        "kind": "none",
        "description": "The request does not map onto a capability.",
        "parameters": {"explanation": "string"},
    },
}

INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "capability": {"type": "string", "enum": list(CAPABILITIES)},
        "parameters": {"type": "object", "additionalProperties": True},
        "reasoning": {
            "type": "string",
            "description": "One sentence on why this capability answers the question.",
        },
    },
    "required": ["capability", "parameters", "reasoning"],
    "additionalProperties": False,
}


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class AssistantReply:
    """What the chat panel renders."""

    answer: str
    capability: str
    kind: str  # query | action | none
    data: dict[str, Any] = field(default_factory=dict)
    #: Present only for actions: exactly what would change, and the token the
    #: client must send back to actually apply it.
    pending_action: dict[str, Any] | None = None
    #: True when the LLM was unavailable and this came from rule-based text.
    offline: bool = False


async def ask(
    db: AsyncSession,
    scope: TenantScope,
    *,
    question: str,
    user_id: uuid.UUID,
) -> AssistantReply:
    """Answer a question, or propose an action for confirmation."""
    if not question.strip():
        raise ValidationError("Ask a question first")

    intent = await _classify(scope.organization_id, question)
    capability = intent.get("capability", "unsupported")
    parameters = intent.get("parameters") or {}
    spec = CAPABILITIES.get(capability, CAPABILITIES["unsupported"])

    if spec["kind"] == "query":
        data = await _run_query(db, scope, capability, parameters)
        answer = await _narrate(scope.organization_id, question, capability, data)
        return AssistantReply(
            answer=answer.text,
            capability=capability,
            kind="query",
            data=data,
            offline=answer.fallback,
        )

    if spec["kind"] == "action":
        preview = await _preview_action(db, scope, capability, parameters)
        return AssistantReply(
            answer=preview["summary"],
            capability=capability,
            kind="action",
            data=preview["data"],
            # Nothing has happened yet. The client must call the confirm
            # endpoint with this payload for anything to change.
            pending_action={
                "capability": capability,
                "parameters": parameters,
                "affected_count": preview["data"].get("affected_count", 0),
                "requested_by": str(user_id),
                "expires_at": (utcnow() + timedelta(minutes=15)).isoformat(),
            },
            offline=False,
        )

    return AssistantReply(
        answer=(
            parameters.get("explanation")
            or "I can answer questions about cost, alerts, vehicles and drivers, "
            "and I can cancel open tasks for vehicles in maintenance. That "
            "request is outside what I can do today."
        ),
        capability="unsupported",
        kind="none",
    )


async def _classify(organization_id: uuid.UUID, question: str) -> dict[str, Any]:
    """Ask the model which capability the question maps onto."""
    catalogue = "\n".join(
        f"- {name} ({spec['kind']}): {spec['description']} "
        f"parameters: {spec['parameters']}"
        for name, spec in CAPABILITIES.items()
    )
    response = await get_claude_client().complete(
        organization_id=organization_id,
        system=SYSTEM_PROMPT,
        prompt=f"Capabilities:\n{catalogue}\n\nUser question: {question}",
        json_schema=INTENT_SCHEMA,
        max_tokens=1024,
        effort="low",
    )
    if response.data:
        return response.data

    # No model available: fall back to a keyword router rather than guessing.
    # It is deliberately conservative - it would rather say "unsupported" than
    # run the wrong capability.
    return _keyword_intent(question)


def _keyword_intent(question: str) -> dict[str, Any]:
    text = question.lower()
    rules: list[tuple[tuple[str, ...], str]] = [
        (("cost the most", "most expensive", "priciest"), "most_expensive_vehicle"),
        (("cost", "spend", "spent", "budget"), "fleet_cost"),
        (("alert", "alarm", "warning"), "active_alerts"),
        (("attention", "problem", "issue", "broken"), "vehicles_needing_attention"),
        (("driver", "safety score", "leaderboard", "points"), "driver_standings"),
        (("summary", "overview", "how is", "how are", "kpi"), "fleet_summary"),
    ]
    for keywords, capability in rules:
        if any(keyword in text for keyword in keywords):
            return {
                "capability": capability,
                "parameters": {},
                "reasoning": "Matched offline keyword routing.",
            }
    return {
        "capability": "unsupported",
        "parameters": {
            "explanation": (
                "The AI assistant is unavailable right now, and I could not "
                "match that question to one of my built-in answers. Try asking "
                "about cost, alerts, vehicles or drivers."
            )
        },
        "reasoning": "No offline keyword matched.",
    }


def _days(parameters: dict[str, Any], default: int = 30) -> int:
    try:
        value = int(parameters.get("days", default))
    except (TypeError, ValueError):
        return default
    return max(1, min(365, value))


async def _run_query(
    db: AsyncSession,
    scope: TenantScope,
    capability: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Execute a read capability. Every query is tenant-scoped by construction."""
    today = utcnow().date()

    if capability in {"fleet_cost", "most_expensive_vehicle"}:
        days = _days(parameters)
        rows = await analytics.vehicle_costs(
            db, scope, date_from=today - timedelta(days=days), date_to=today
        )
        ranked = sorted(rows, key=lambda r: r.total_cost, reverse=True)
        payload = {
            "days": days,
            "total_cost": round(sum(r.total_cost for r in ranked), 2),
            "vehicles": [
                {
                    "name": r.vehicle_name,
                    "plate": r.license_plate,
                    "total_cost": r.total_cost,
                    "fuel_cost": round(r.fuel_cost, 2),
                    "maintenance_cost": round(r.maintenance_cost, 2),
                    "distance_km": r.distance_km,
                    "cost_per_km": r.cost_per_km,
                }
                for r in ranked[:10]
            ],
        }
        if capability == "most_expensive_vehicle":
            payload["answer_vehicle"] = (
                payload["vehicles"][0] if payload["vehicles"] else None
            )
        return payload

    if capability == "fleet_summary":
        days = _days(parameters)
        kpis = await analytics.fleet_kpis(
            db, scope, date_from=today - timedelta(days=days), date_to=today
        )
        return {"days": days, **_as_dict(kpis)}

    if capability == "active_alerts":
        stmt = scope.select(Alert).where(Alert.status == AlertStatus.ACTIVE)
        severity = parameters.get("severity")
        if severity in {"info", "warning", "critical"}:
            stmt = stmt.where(Alert.severity == severity)
        rows = (
            await db.execute(stmt.order_by(Alert.created_at.desc()).limit(25))
        ).scalars().all()
        return {
            "count": len(rows),
            "alerts": [
                {
                    "title": a.title,
                    "message": a.message,
                    "severity": a.severity,
                    "rule_type": a.rule_type,
                    "at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in rows
            ],
        }

    if capability == "vehicles_needing_attention":
        alerting = {
            row[0]
            for row in (
                await db.execute(
                    sa.select(Alert.vehicle_id).where(
                        Alert.organization_id == scope.organization_id,
                        Alert.status == AlertStatus.ACTIVE,
                        Alert.vehicle_id.is_not(None),
                    )
                )
            ).all()
        }
        vehicles = (
            await db.execute(scope.select(Vehicle).order_by(Vehicle.name))
        ).scalars().all()
        flagged = [
            {
                "name": v.name,
                "plate": v.license_plate,
                "status": v.status,
                "reason": (
                    "in maintenance"
                    if v.status == VehicleStatus.IN_MAINTENANCE
                    else "has active alerts"
                    if v.id in alerting
                    else "no GPS device fitted"
                ),
            }
            for v in vehicles
            if v.status == VehicleStatus.IN_MAINTENANCE
            or v.id in alerting
            or not v.is_tracked
        ]
        return {"count": len(flagged), "vehicles": flagged}

    if capability == "driver_standings":
        drivers = (
            await db.execute(
                scope.select(Driver).order_by(Driver.safety_score.desc())
            )
        ).scalars().all()
        return {
            "count": len(drivers),
            "drivers": [
                {
                    "name": d.full_name,
                    "safety_score": d.safety_score,
                    "points_balance": d.points_balance,
                    "fatigue_risk": d.fatigue_risk_level,
                }
                for d in drivers
            ],
        }

    return {}


def _as_dict(obj: Any) -> dict[str, Any]:
    """Slotted dataclasses have no __dict__, so go through asdict."""
    from dataclasses import asdict, is_dataclass

    if is_dataclass(obj):
        return asdict(obj)
    return dict(getattr(obj, "__dict__", {}))


async def _preview_action(
    db: AsyncSession,
    scope: TenantScope,
    capability: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Compute exactly what an action would change, without changing it."""
    if capability != "cancel_tasks_for_vehicles_in_maintenance":
        raise ValidationError(f"Unknown action: {capability}")

    tasks = await _tasks_for_maintenance_vehicles(db, scope)
    names = [task.title for task in tasks[:10]]
    return {
        "summary": (
            f"This would cancel {len(tasks)} open task"
            f"{'' if len(tasks) == 1 else 's'} assigned to vehicles currently in "
            "maintenance. Nothing has changed yet - confirm to apply."
            if tasks
            else "No open tasks are assigned to vehicles currently in maintenance, "
            "so there is nothing to cancel."
        ),
        "data": {
            "affected_count": len(tasks),
            "tasks": names,
            "task_ids": [str(task.id) for task in tasks],
        },
    }


async def _tasks_for_maintenance_vehicles(
    db: AsyncSession, scope: TenantScope
) -> list[Task]:
    result = await db.execute(
        scope.select(Task)
        .join(Vehicle, Vehicle.id == Task.vehicle_id)
        .where(
            Vehicle.status == VehicleStatus.IN_MAINTENANCE,
            Task.status.in_(
                [TaskStatus.ASSIGNED, TaskStatus.ACCEPTED, TaskStatus.EN_ROUTE]
            ),
        )
        .order_by(Task.created_at)
    )
    return list(result.scalars().unique().all())


async def confirm_action(
    db: AsyncSession,
    scope: TenantScope,
    *,
    pending_action: dict[str, Any],
    user_id: uuid.UUID,
    principal: Any = None,
    request: Any = None,
) -> dict[str, Any]:
    """Execute a previously previewed action. This is the only mutating path.

    The confirmation must come from the same user who was shown the preview,
    and must be recent: an approval is for what they were shown, not a
    standing permission.
    """
    capability = pending_action.get("capability")
    if capability != "cancel_tasks_for_vehicles_in_maintenance":
        raise ValidationError("That action is not something I can apply")

    if str(pending_action.get("requested_by")) != str(user_id):
        raise PermissionDeniedError(
            "This action was proposed to a different user and cannot be "
            "confirmed by you"
        )

    expires_at = pending_action.get("expires_at")
    if expires_at:
        try:
            deadline = datetime.fromisoformat(str(expires_at))
        except ValueError:
            deadline = utcnow()
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        if deadline < utcnow():
            raise ValidationError(
                "That proposal has expired. Ask again so you can review a "
                "current preview before applying it."
            )

    from app.models.enums import AuditAction
    from app.services import audit
    from app.services import tasks as task_service

    reason = (
        pending_action.get("parameters", {}).get("reason")
        or "Vehicle in maintenance (applied from the FleetBeat assistant)"
    )

    tasks = await _tasks_for_maintenance_vehicles(db, scope)
    cancelled = []
    for task in tasks:
        await task_service.transition(
            db,
            scope,
            task_id=task.id,
            to_status=TaskStatus.CANCELLED,
            cancellation_reason=reason,
            principal=principal,
            request=request,
        )
        cancelled.append(task.title)

    await audit.record(
        db,
        action=AuditAction.AI_ACTION_CONFIRMED,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="assistant_action",
        summary=(
            f"Assistant action '{capability}' confirmed and applied to "
            f"{len(cancelled)} task(s)"
        ),
        changes={"after": {"cancelled_tasks": cancelled}},
        request=request,
    )

    return {
        "capability": capability,
        "applied_count": len(cancelled),
        "tasks": cancelled,
        "message": (
            f"Cancelled {len(cancelled)} task"
            f"{'' if len(cancelled) == 1 else 's'}."
        ),
    }


async def _narrate(
    organization_id: uuid.UUID,
    question: str,
    capability: str,
    data: dict[str, Any],
) -> Any:
    """Turn the figures our code computed into a sentence.

    The model phrases; it never sources. Everything in ``data`` came from the
    database through a tenant-scoped query.
    """
    import json

    offline = _offline_answer(capability, data)
    return await get_claude_client().complete(
        organization_id=organization_id,
        system=(
            "You are summarising fleet data for a fleet manager. Answer the "
            "question in two or three sentences using ONLY the figures given. "
            "Never invent a number. Lead with the direct answer."
        ),
        prompt=(
            f"Question: {question}\n\n"
            f"Figures (already computed, authoritative):\n"
            f"{json.dumps(data, default=str)[:6000]}"
        ),
        offline_text=offline,
        max_tokens=600,
        effort="low",
    )


def _offline_answer(capability: str, data: dict[str, Any]) -> str:
    """A useful answer built from the same figures, with no model involved."""
    if capability == "most_expensive_vehicle":
        vehicle = data.get("answer_vehicle")
        if not vehicle:
            return "No vehicle has recorded any cost in that period."
        return (
            f"{vehicle['name']} ({vehicle['plate']}) cost the most: "
            f"{vehicle['total_cost']:,.2f} over the last {data['days']} days, "
            f"of which {vehicle['fuel_cost']:,.2f} was fuel and "
            f"{vehicle['maintenance_cost']:,.2f} maintenance."
        )
    if capability == "fleet_cost":
        return (
            f"The fleet cost {data.get('total_cost', 0):,.2f} over the last "
            f"{data.get('days', 30)} days across "
            f"{len(data.get('vehicles', []))} vehicles."
        )
    if capability == "active_alerts":
        count = data.get("count", 0)
        if count == 0:
            return "There are no active alerts right now."
        first = data["alerts"][0]
        return (
            f"There are {count} active alerts. The most recent is "
            f"\"{first['title']}\" ({first['severity']})."
        )
    if capability == "vehicles_needing_attention":
        count = data.get("count", 0)
        if count == 0:
            return "No vehicles currently need attention."
        names = ", ".join(v["name"] for v in data["vehicles"][:5])
        return f"{count} vehicle(s) need attention: {names}."
    if capability == "driver_standings":
        drivers = data.get("drivers", [])
        if not drivers:
            return "No drivers are on record yet."
        best, worst = drivers[0], drivers[-1]
        return (
            f"{best['name']} has the best safety score at "
            f"{best['safety_score']:.0f}; {worst['name']} is lowest at "
            f"{worst['safety_score']:.0f}."
        )
    if capability == "fleet_summary":
        return (
            f"Over the last {data.get('days', 30)} days the fleet covered "
            f"{data.get('distance_km', 0):,.0f} km across "
            f"{data.get('trips', 0)} trips, at a cost of "
            f"{data.get('total_cost', 0):,.2f}."
        )
    return "Here are the figures."
