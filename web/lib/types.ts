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
