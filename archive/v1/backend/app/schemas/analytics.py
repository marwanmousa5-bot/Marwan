"""Analytics, cost, sustainability and rewards schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class VehicleCostOut(BaseModel):
    vehicle_id: uuid.UUID
    vehicle_name: str
    license_plate: str
    fuel_cost: float
    maintenance_cost: float
    compliance_cost: float
    depreciation: float
    total_cost: float
    distance_km: float
    cost_per_km: float | None = None


class FleetKpisOut(BaseModel):
    total_vehicles: int
    active_vehicles: int
    tracked_vehicles: int
    total_drivers: int
    trips: int
    distance_km: float
    driving_hours: float
    utilisation_percent: float
    total_cost: float
    cost_per_km: float | None = None
    fuel_cost: float
    maintenance_cost: float
    co2_kg: float
    active_alerts: int
    violations: int
    average_safety_score: float


class TrendPointOut(BaseModel):
    period: str
    distance_km: float
    cost: float
    co2_kg: float
    violations: int


class EvCandidateOut(BaseModel):
    vehicle_id: uuid.UUID
    vehicle_name: str
    license_plate: str
    days_observed: int
    average_daily_km: float
    max_daily_km: float
    assumed_range_km: float
    annual_fuel_cost: float
    rationale: str


class AssetSummaryOut(BaseModel):
    vehicle_id: uuid.UUID
    vehicle_name: str
    purchase_value: float | None = None
    age_years: float | None = None
    annual_depreciation: float | None = None
    book_value: float | None = None
    odometer_km: float
    replacement_recommended: bool
    reasons: list[str]


class AnomalyOut(BaseModel):
    kind: str
    vehicle_id: uuid.UUID
    vehicle_name: str
    value: float
    mean: float
    z_score: float
    summary: str
    observed_at: datetime | None = None


class MaintenanceForecastOut(BaseModel):
    vehicle_id: uuid.UUID
    vehicle_name: str
    schedule_id: uuid.UUID
    schedule_name: str
    predicted_due_on: date
    days_away: int
    daily_km: float
    remaining_km: float | None = None
    basis: str
    summary: str


# ---------------------------------------------------------------------------
# Rewards (Section 4g)
# ---------------------------------------------------------------------------

class LeaderboardRow(BaseModel):
    rank: int
    driver_id: uuid.UUID
    driver_name: str
    points_balance: int
    safety_score: float
    fatigue_risk_level: str
    badges: list[str]


class BadgeDefinition(BaseModel):
    code: str
    name: str
    description: str


class LeaderboardOut(BaseModel):
    period: str
    rows: list[LeaderboardRow]
    badge_catalogue: list[BadgeDefinition]
    #: False for drivers when their Organization has not opted in.
    visible_to_drivers: bool


class PointsLedgerEntryOut(ORMModel):
    id: uuid.UUID
    driver_id: uuid.UUID
    delta: int
    balance_after: int
    reason: str
    period_month: str
    created_at: datetime


class DriverScoreOut(BaseModel):
    driver_id: uuid.UUID
    driver_name: str
    safety_score: float
    score_band: str
    provisional: bool
    distance_km: float
    violations: dict[str, int]
    fatigue_risk_level: str
    fatigue_reasons: list[str]
    points_balance: int
