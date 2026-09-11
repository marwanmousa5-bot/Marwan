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
