/** Shapes mirrored from the FastAPI OpenAPI schema. */

export type UserRole = "super_admin" | "org_admin" | "dispatcher" | "driver";
export type UserStatus = "pending_activation" | "active" | "suspended";
export type OrganizationStatus = "active" | "suspended";
export type VehicleLiveStatus = "moving" | "idle" | "alert" | "not_tracked";
export type DeviceStatus =
  | "in_stock"
  | "assigned"
  | "active"
  | "faulty"
  | "retired";

export interface User {
  id: string;
  organization_id: string | null;
  email: string;
  full_name: string;
  phone: string | null;
  role: UserRole;
  status: UserStatus;
  must_change_password: boolean;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface CurrentUser {
  user: User;
  organization_name: string | null;
  organization_timezone: string | null;
  is_impersonating: boolean;
}

export interface Session extends CurrentUser {
  tokens: TokenPair;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  industry: string | null;
  timezone: string;
  contact_name: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  logo_url: string | null;
  status: OrganizationStatus;
  plan: string;
  subscription_status: string;
  created_at: string;
}

export interface OrganizationHealth {
  organization: Organization;
  vehicle_count: number;
  active_device_count: number;
  user_count: number;
  last_login_at: string | null;
}

export interface OrganizationProvisionResult {
  organization: Organization;
  admin_user: User;
  activation_url: string;
}

export interface PlatformOverview {
  total_organizations: number;
  active_organizations: number;
  total_vehicles: number;
  total_drivers: number;
  total_users: number;
  total_devices: number;
  active_devices: number;
  devices_in_stock: number;
}

export interface VehicleDevice {
  id: string;
  serial_number: string;
  model: string | null;
  status: DeviceStatus;
  last_signal_at: string | null;
}

export interface Vehicle {
  id: string;
  organization_id: string;
  name: string;
  make: string | null;
  model: string | null;
  year: number | null;
  vin: string | null;
  license_plate: string;
  vehicle_type: string;
  fuel_type: string;
  ownership: string;
  status: string;
  odometer_km: number;
  last_latitude: number | null;
  last_longitude: number | null;
  last_heading: number | null;
  last_speed_kph: number | null;
  last_position_at: string | null;
  stopped_since: string | null;
  is_tracked: boolean;
  device: VehicleDevice | null;
  live_status: VehicleLiveStatus;
  created_at: string;
  updated_at: string;
}

export interface Driver {
  id: string;
  organization_id: string;
  user_id: string | null;
  full_name: string;
  employee_number: string | null;
  phone: string | null;
  license_number: string | null;
  license_expiry: string | null;
  employment_status: string;
  assigned_vehicle_id: string | null;
  safety_score: number;
  fatigue_risk_level: string;
  points_balance: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// ---------------------------------------------------------------------------
// Phase 2: live tracking, map tools, alerts and operations
// ---------------------------------------------------------------------------

export type AlertSeverity = "info" | "warning" | "critical";
export type AlertStatus = "active" | "acknowledged" | "resolved";
export type GeofenceShape = "polygon" | "circle";
export type GeofenceTrigger = "on_enter" | "on_exit" | "both";
export type PoiCategory = "depot" | "customer_site" | "fuel_station" | "custom";
export type WorkOrderStatus =
  | "proposed"
  | "open"
  | "in_progress"
  | "completed"
  | "cancelled";

export interface LiveVehicle {
  id: string;
  name: string;
  license_plate: string;
  live_status: VehicleLiveStatus;
  latitude: number | null;
  longitude: number | null;
  heading: number | null;
  speed_kph: number | null;
  last_position_at: string | null;
  stopped_since: string | null;
  is_tracked: boolean;
  device_serial: string | null;
  device_last_signal_at: string | null;
  driver_id: string | null;
  driver_name: string | null;
  active_alert_count: number;
}

export interface LiveKpis {
  total_vehicles: number;
  active_now: number;
  idle: number;
  not_tracked: number;
  active_alerts: number;
  distance_today_km: number;
}

export interface LiveSnapshot {
  vehicles: LiveVehicle[];
  kpis: LiveKpis;
  server_time: string;
}

/** Messages pushed over the live WebSocket feed. */
export type LiveMessage =
  | { type: "connected"; organization_id: string }
  | { type: "pong" }
  | {
      type: "position";
      vehicle_id: string;
      lat: number;
      lng: number;
      speed_kph: number;
      heading: number;
      moving: boolean;
      trip_id: string | null;
      at: string;
    }
  | { type: "trip.started" | "trip.ended"; vehicle_id: string; trip_id: string; at: string }
  | {
      type: "alert";
      id: string;
      rule_type: string;
      severity: AlertSeverity;
      title: string;
      message: string;
      vehicle_id: string | null;
      status: AlertStatus;
      at: string;
    };

export interface Alert {
  id: string;
  organization_id: string;
  rule_type: string;
  severity: AlertSeverity;
  status: AlertStatus;
  title: string;
  message: string;
  vehicle_id: string | null;
  driver_id: string | null;
  subject_type: string | null;
  subject_id: string | null;
  context: Record<string, unknown> | null;
  created_at: string;
}

export interface AlertRule {
  id: string;
  rule_type: string;
  is_enabled: boolean;
  severity: AlertSeverity;
  parameters: Record<string, unknown> | null;
}

export interface Geofence {
  id: string;
  organization_id: string;
  name: string;
  shape: GeofenceShape;
  geometry: {
    coordinates?: [number, number][];
    center?: [number, number];
    radius_m?: number;
  };
  color: string;
  trigger: GeofenceTrigger;
  is_active: boolean;
  vehicle_ids: string[];
  created_at: string;
}

export interface Poi {
  id: string;
  organization_id: string;
  name: string;
  category: PoiCategory;
  latitude: number;
  longitude: number;
  address: string | null;
  notes: string | null;
  created_at: string;
}

export interface WeatherZone {
  id: string;
  latitude: number;
  longitude: number;
  radius_m: number;
  condition: string;
  severity: string;
  expected_delay_minutes: number;
  observed_at: string;
}

export interface Trip {
  id: string;
  vehicle_id: string;
  driver_id: string | null;
  status: "in_progress" | "completed" | "cancelled";
  started_at: string;
  ended_at: string | null;
  distance_km: number;
  duration_seconds: number;
  average_speed_kph: number;
  max_speed_kph: number;
  idle_seconds: number;
}

export interface TripPoint {
  lat: number;
  lng: number;
  speed_kph: number;
  heading: number;
  at: string;
}

export interface TripEventMarker {
  id: string;
  event_type: string;
  severity: string;
  at: string;
  lat: number | null;
  lng: number | null;
  speed_kph: number | null;
}

export interface TripPlayback {
  trip: Trip;
  vehicle_name: string;
  driver_name: string | null;
  points: TripPoint[];
  events: TripEventMarker[];
}

export interface MaintenanceSchedule {
  id: string;
  vehicle_id: string;
  name: string;
  component: string | null;
  interval_type: "mileage" | "time";
  interval_km: number | null;
  interval_days: number | null;
  next_due_odometer_km: number | null;
  next_due_date: string | null;
  is_active: boolean;
}

export interface WorkOrder {
  id: string;
  vehicle_id: string;
  schedule_id: string | null;
  title: string;
  description: string | null;
  status: WorkOrderStatus;
  scheduled_for: string | null;
  completed_at: string | null;
  odometer_km: number | null;
  labour_cost: number | null;
  parts_cost: number | null;
  total_cost: number | null;
  vendor: string | null;
  created_by_copilot: boolean;
}

export interface FuelLog {
  id: string;
  vehicle_id: string;
  driver_id: string | null;
  fuel_type: string;
  quantity: number;
  unit: string;
  total_cost: number;
  odometer_km: number | null;
  filled_at: string;
  location_name: string | null;
  co2_kg: number | null;
}

export interface FuelSummaryRow {
  vehicle_id: string;
  vehicle_name: string;
  entries: number;
  total_quantity: number;
  total_cost: number;
  total_co2_kg: number;
  litres_per_100km: number | null;
}

export interface ComplianceDocument {
  id: string;
  document_type: string;
  title: string;
  reference_number: string | null;
  issuer: string | null;
  vehicle_id: string | null;
  driver_id: string | null;
  issued_on: string | null;
  expires_on: string | null;
  cost: number | null;
  file_url: string | null;
  days_until_expiry: number | null;
}

export interface PlatformDevice {
  id: string;
  serial_number: string;
  imei: string | null;
  model: string | null;
  status: DeviceStatus;
  organization_id: string | null;
  vehicle_id: string | null;
  assigned_at: string | null;
  last_signal_at: string | null;
  created_at: string;
  organization_name: string | null;
  vehicle_name: string | null;
  vehicle_plate: string | null;
}

// ---------------------------------------------------------------------------
// Phase 3: dispatch tasks, inspections and incidents
// ---------------------------------------------------------------------------

export type TaskStatus =
  | "assigned"
  | "accepted"
  | "en_route"
  | "completed"
  | "cancelled";
export type TaskPriority = "normal" | "urgent";
export type TaskType = "delivery" | "pickup" | "service_call" | "custom";

export interface Task {
  id: string;
  organization_id: string;
  title: string;
  description: string | null;
  task_type: TaskType;
  priority: TaskPriority;
  status: TaskStatus;
  driver_id: string | null;
  vehicle_id: string | null;
  destination_label: string | null;
  destination_latitude: number;
  destination_longitude: number;
  waypoints: { lat: number; lng: number; label?: string | null }[] | null;
  due_at: string | null;
  eta: string | null;
  accepted_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  completion_note: string | null;
  completion_photo_url: string | null;
  route_id: string | null;
  trip_id: string | null;
  created_at: string;
  driver_name: string | null;
  vehicle_name: string | null;
}

export interface RoutePreview {
  distance_km: number;
  duration_minutes: number;
  eta: string;
  geometry_polyline: string | null;
}

export interface Incident {
  id: string;
  title: string;
  description: string | null;
  severity: "minor" | "moderate" | "severe";
  status: "reported" | "under_review" | "closed";
  vehicle_id: string | null;
  driver_id: string | null;
  task_id: string | null;
  occurred_at: string;
  latitude: number | null;
  longitude: number | null;
  location_label: string | null;
  created_at: string;
  photo_urls: string[];
}

// ---------------------------------------------------------------------------
// Phase 4: analytics, sustainability and rewards
// ---------------------------------------------------------------------------

export interface FleetKpis {
  total_vehicles: number;
  active_vehicles: number;
  tracked_vehicles: number;
  total_drivers: number;
  trips: number;
  distance_km: number;
  driving_hours: number;
  utilisation_percent: number;
  total_cost: number;
  cost_per_km: number | null;
  fuel_cost: number;
  maintenance_cost: number;
  co2_kg: number;
  active_alerts: number;
  violations: number;
  average_safety_score: number;
}

export interface TrendPoint {
  period: string;
  distance_km: number;
  cost: number;
  co2_kg: number;
  violations: number;
}

export interface EvCandidate {
  vehicle_id: string;
  vehicle_name: string;
  license_plate: string;
  days_observed: number;
  average_daily_km: number;
  max_daily_km: number;
  assumed_range_km: number;
  annual_fuel_cost: number;
  rationale: string;
}

export interface AssetSummary {
  vehicle_id: string;
  vehicle_name: string;
  purchase_value: number | null;
  age_years: number | null;
  annual_depreciation: number | null;
  book_value: number | null;
  odometer_km: number;
  replacement_recommended: boolean;
  reasons: string[];
}

export interface AnalyticsAnomaly {
  kind: string;
  vehicle_id: string;
  vehicle_name: string;
  value: number;
  mean: number;
  z_score: number;
  summary: string;
  observed_at: string | null;
}

export interface MaintenanceForecast {
  vehicle_id: string;
  vehicle_name: string;
  schedule_id: string;
  schedule_name: string;
  predicted_due_on: string;
  days_away: number;
  daily_km: number;
  remaining_km: number | null;
  basis: string;
  summary: string;
}

export interface LeaderboardRow {
  rank: number;
  driver_id: string;
  driver_name: string;
  points_balance: number;
  safety_score: number;
  fatigue_risk_level: string;
  badges: string[];
}

export interface BadgeDefinition {
  code: string;
  name: string;
  description: string;
}

export interface Leaderboard {
  period: string;
  rows: LeaderboardRow[];
  badge_catalogue: BadgeDefinition[];
  visible_to_drivers: boolean;
}

export interface DriverScore {
  driver_id: string;
  driver_name: string;
  safety_score: number;
  score_band: string;
  provisional: boolean;
  distance_km: number;
  violations: Record<string, number>;
  fatigue_risk_level: string;
  fatigue_reasons: string[];
  points_balance: number;
}

export interface PointsLedgerEntry {
  id: string;
  driver_id: string;
  delta: number;
  balance_after: number;
  reason: string;
  period_month: string;
  created_at: string;
}

// --- Phase 5: assistant, copilot, reports -----------------------------------

/**
 * An action the assistant has *proposed*. Nothing has changed until this
 * exact object is sent back to /assistant/confirm (Section 9).
 */
export interface PendingAction {
  capability: string;
  parameters: Record<string, unknown>;
  affected_count: number;
  requested_by: string;
  expires_at: string;
}

export interface AssistantReply {
  answer: string;
  capability: string;
  kind: string;
  data: Record<string, unknown>;
  pending_action: PendingAction | null;
  offline: boolean;
}

export interface AssistantActionResult {
  capability: string;
  applied_count: number;
  tasks: string[];
  message: string;
}

export type RecommendationKind =
  | "copilot"
  | "maintenance_window"
  | "reroute"
  | "ev_transition"
  | "anomaly";

export type RecommendationStatus = "pending" | "dismissed" | "applied" | "expired";

export interface Recommendation {
  id: string;
  kind: RecommendationKind;
  status: RecommendationStatus;
  rank: number;
  title: string;
  summary: string;
  suggested_action: string | null;
  estimated_benefit: string | null;
  action_payload: Record<string, unknown> | null;
  signals: Record<string, unknown> | null;
  vehicle_id: string | null;
  driver_id: string | null;
  task_id: string | null;
  created_at: string;
}

export interface MaintenanceProposal {
  vehicle_id: string;
  vehicle_name: string;
  schedule_id: string;
  schedule_name: string;
  proposed_date: string;
  rationale: string;
  tasks_that_day: number;
  auto_booked: boolean;
  work_order_id: string | null;
}

export interface ReportSummary {
  id: string;
  period_type: string;
  period_start: string;
  period_end: string;
  summary_text: string;
  metrics: Record<string, number | string> | null;
  generated_by: string;
  created_at: string;
}
