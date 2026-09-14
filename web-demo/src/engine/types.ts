// FleetBeat domain model. Mirrors the FastAPI/PostgreSQL schema so the browsable
// build and the server build describe the same product.

export type Role = 'org_admin' | 'dispatcher' | 'driver' | 'super_admin';

export type VehicleStatus =
  | 'moving' | 'idle' | 'stopped' | 'offline' | 'maintenance' | 'not_tracked';
export type Lifecycle =
  | 'planned' | 'acquired' | 'active' | 'maintenance' | 'suspended' | 'retired';
export type VehicleType =
  | 'van' | 'truck' | 'car' | 'refrigerated_van' | 'cargo_bike' | 'ev_van';
export type FuelKind = 'diesel' | 'petrol' | 'electric' | 'hybrid';
export type Severity = 'low' | 'medium' | 'high' | 'critical';

export type TaskStatus =
  | 'unassigned' | 'assigned' | 'accepted' | 'en_route' | 'arrived'
  | 'in_progress' | 'completed' | 'delayed' | 'failed' | 'cancelled';
export type Priority = 'low' | 'normal' | 'high' | 'urgent';
export type SlaState = 'none' | 'on_track' | 'at_risk' | 'breached' | 'met';
export type TaskKind =
  | 'delivery' | 'pickup' | 'service_call' | 'inspection' | 'collection' | 'custom';

export type AlertStatus =
  | 'triggered' | 'acknowledged' | 'investigating' | 'snoozed'
  | 'escalated' | 'resolved' | 'suppressed';
export type AlertCategory =
  | 'vehicle' | 'driver' | 'route' | 'maintenance' | 'compliance'
  | 'geofence' | 'security';

export type MaintenanceStatus =
  | 'healthy' | 'due_soon' | 'due' | 'overdue' | 'critical' | 'in_workshop';
export type WorkOrderStatus =
  | 'requested' | 'approved' | 'scheduled' | 'in_progress'
  | 'waiting_for_parts' | 'completed' | 'cancelled';

export type DriverStatus =
  | 'available' | 'driving' | 'on_break' | 'off_duty' | 'unavailable';

export type IncidentStatus =
  | 'reported' | 'under_investigation' | 'action_required' | 'resolved' | 'closed';

export type DocStatus = 'valid' | 'expiring_soon' | 'expired';

export interface Org {
  id: string;
  name: string;
  city: string;
  country: string;
  settings: OrgSettings;
}

export interface OrgSettings {
  currency: string;
  fuelPricePerLitre: number;
  energyPricePerKwh: number;
  co2PerLitreDiesel: number;
  co2PerLitrePetrol: number;
  co2PerKwh: number;
  showLeaderboardToDrivers: boolean;
  driverPointsStart: number;
  driverPoints: Record<string, number>;
  safetyWeights: Record<string, number>;
  gpsLiveThresholdS: number;
  gpsStaleThresholdS: number;
  documentAlertDays: number[];
  maintenanceDueSoonKm: number;
  maintenanceDueSoonDays: number;
  alertEscalationMinutes: number[];
  slaAtRiskMinutes: number;
  maintenanceHealthWeights: Record<string, number>;
  evCandidateDailyKm: number;
  labourRate: number;
}

export interface User {
  id: string;
  email: string;
  fullName: string;
  role: Role;
  avatarColor: string;
  driverId?: string;
}

export interface Vehicle {
  id: string;
  name: string;
  plate: string;
  vin: string;
  type: VehicleType;
  make: string;
  model: string;
  year: number;
  colour: string;
  fuelType: FuelKind;
  lifecycle: Lifecycle;
  odometerKm: number;
  tankCapacityL?: number;
  avgConsumption?: number;      // L/100km
  batteryCapacityKwh?: number;
  stateOfChargePct?: number;
  rangeKm?: number;
  chargingStatus?: string;
  ownership: 'owned' | 'leased';
  purchaseDate: string;
  purchaseValue: number;
  residualValue: number;
  depreciationYears: number;
  annualInsurance: number;
  annualRegistration: number;
  driverId?: string;
  deviceId?: string;
  homePlaceId?: string;
  // live telemetry - the single source of truth for "where is it now"
  lat?: number;
  lon?: number;
  heading: number;
  speedKph: number;
  lastPositionAt?: number;
  street?: string;
  satellites: number;
  ignitionOn: boolean;
  idleSince?: number;
  retiredAt?: number;
  notes?: string;
}

export interface Device {
  id: string;
  serial: string;
  imei: string;
  model: string;
  firmware: string;
  status: 'in_stock' | 'assigned' | 'active' | 'faulty' | 'retired';
  orgId?: string;
  vehicleId?: string;
  lastSignalAt?: number;
}

export interface Driver {
  id: string;
  employeeNo: string;
  fullName: string;
  email: string;
  phone: string;
  status: DriverStatus;
  licenseNumber: string;
  licenseClass: string;
  licenseExpiry: string;
  hiredOn: string;
  safetyScore: number;
  previousSafetyScore: number;
  points: number;
  dutyHoursToday: number;
  shiftStart: string;
  shiftEnd: string;
  avatarColor: string;
  userId?: string;
}

export interface Place {
  id: string;
  name: string;
  category: 'depot' | 'customer_site' | 'fuel_station' | 'workshop' | 'parking' | 'custom';
  address?: string;
  lat: number;
  lon: number;
  contactName?: string;
  contactPhone?: string;
  active: boolean;
}

export interface Customer {
  id: string;
  name: string;
  contactName: string;
  contactPhone: string;
  placeId: string;
  accountRef: string;
}

export interface Geofence {
  id: string;
  name: string;
  kind: 'polygon' | 'circle';
  trigger: 'enter' | 'exit' | 'both';
  colour: string;
  polygon?: [number, number][];
  centreLat?: number;
  centreLon?: number;
  radiusM?: number;
  vehicleIds: string[];
  active: boolean;
  restricted: boolean;
  description?: string;
}

export interface RouteStop {
  id: string;
  sequence: number;
  name: string;
  lat: number;
  lon: number;
  kind: string;
  serviceMinutes: number;
  plannedArrival?: number;
  arrivedAt?: number;
  taskId?: string;
  notes?: string;
}

export interface Route {
  id: string;
  name: string;
  vehicleId?: string;
  driverId?: string;
  originLat: number;
  originLon: number;
  originName: string;
  destLat: number;
  destLon: number;
  destName: string;
  geometry: [number, number][];
  distanceM: number;
  durationS: number;
  legs: { distanceM: number; durationS: number }[];
  stops: RouteStop[];
  active: boolean;
  optimized: boolean;
  avoidEdges: number[];
  startedAt?: number;
}

export interface Trip {
  id: string;
  reference: string;
  vehicleId: string;
  driverId?: string;
  routeId?: string;
  taskId?: string;
  status: 'active' | 'completed';
  startedAt: number;
  endedAt?: number;
  startLat: number;
  startLon: number;
  startAddress: string;
  endLat?: number;
  endLon?: number;
  endAddress?: string;
  distanceKm: number;
  durationS: number;
  idleS: number;
  avgSpeedKph: number;
  maxSpeedKph: number;
  stopCount: number;
  eventCount: number;
  fuelUsedL: number;
  energyUsedKwh: number;
  co2Kg: number;
  startOdometerKm: number;
  endOdometerKm?: number;
  positions: TripPosition[];
}

export interface TripPosition {
  t: number;              // ms epoch
  lat: number;
  lon: number;
  speedKph: number;
  heading: number;
  odometerKm: number;
  street?: string;
  ignition: boolean;
}

export interface Task {
  id: string;
  reference: string;
  title: string;
  description?: string;
  kind: TaskKind;
  status: TaskStatus;
  priority: Priority;
  customerId?: string;
  placeId?: string;
  contactName?: string;
  contactPhone?: string;
  address: string;
  lat: number;
  lon: number;
  driverId?: string;
  vehicleId?: string;
  routeId?: string;
  scheduledFor?: number;
  windowStart?: number;
  windowEnd?: number;
  slaDueAt?: number;
  slaMinutes?: number;
  slaState: SlaState;
  eta?: number;
  serviceMinutes: number;
  assignedAt?: number;
  acceptedAt?: number;
  startedAt?: number;
  arrivedAt?: number;
  completedAt?: number;
  cancelledAt?: number;
  failedAt?: number;
  instructions?: string;
  failureReason?: string;
  failureNote?: string;
  cancelReason?: string;
  pod?: {
    recipient: string;
    notes?: string;
    signature?: string;
    photo?: string;
    lat: number;
    lon: number;
    at: number;
  };
  createdAt: number;
}

export interface AlertRule {
  id: string;
  code: string;
  name: string;
  category: AlertCategory;
  severity: Severity;
  description: string;
  metric: string;
  operator: string;
  threshold?: number;
  thresholdUnit?: string;
  durationS: number;
  vehicleIds: string[];
  driverIds: string[];
  notifyRoles: Role[];
  notifyChannels: string[];
  escalationMinutes: number[];
  cooldownS: number;
  dedupeWindowS: number;
  recommendedAction?: string;
  active: boolean;
  system: boolean;
}

export interface Alert {
  id: string;
  ruleId?: string;
  code: string;
  category: AlertCategory;
  severity: Severity;
  status: AlertStatus;
  title: string;
  detail?: string;
  recommendedAction?: string;
  vehicleId?: string;
  driverId?: string;
  tripId?: string;
  taskId?: string;
  geofenceId?: string;
  workOrderId?: string;
  documentId?: string;
  lat?: number;
  lon?: number;
  street?: string;
  evidence: Record<string, unknown>;
  triggeredAt: number;
  acknowledgedAt?: number;
  acknowledgedBy?: string;
  assignedTo?: string;
  resolvedAt?: number;
  resolvedBy?: string;
  resolutionNote?: string;
  snoozedUntil?: number;
  escalatedAt?: number;
  escalationLevel: number;
  occurrences: number;
  firstOccurrenceAt: number;
  lastOccurrenceAt: number;
  dedupeKey: string;
}

export type DriverEventType =
  | 'overspeed' | 'harsh_braking' | 'harsh_acceleration' | 'harsh_cornering'
  | 'idling' | 'route_deviation' | 'geofence_breach'
  | 'clean_streak' | 'eco_driving' | 'improvement';

export interface DriverEvent {
  id: string;
  driverId: string;
  vehicleId?: string;
  tripId?: string;
  alertId?: string;
  kind: DriverEventType;
  severity: Severity;
  occurredAt: number;
  lat?: number;
  lon?: number;
  street?: string;
  value?: number;
  threshold?: number;
  durationS?: number;
  detail?: string;
}

export interface PointTransaction {
  id: string;
  driverId: string;
  points: number;
  balanceAfter: number;
  reason: string;
  detail?: string;
  occurredAt: number;
}

export interface BadgeAward {
  id: string;
  driverId: string;
  code: string;
  name: string;
  description: string;
  icon: string;
  awardedAt: number;
  period: string;
}

export interface MaintenanceSchedule {
  id: string;
  vehicleId: string;
  name: string;
  category: string;
  intervalKm?: number;
  intervalMonths?: number;
  lastServiceKm?: number;
  lastServiceDate?: string;
  dueAtKm?: number;
  dueAtDate?: string;
  status: MaintenanceStatus;
  priority: Priority;
  estimatedCost: number;
  estimatedMinutes: number;
  active: boolean;
  lastAlertedStatus?: MaintenanceStatus;
}

export interface WorkOrderPart {
  id: string;
  name: string;
  sku: string;
  quantity: number;
  unitCost: number;
  supplier: string;
  warrantyMonths?: number;
}

export interface WorkOrder {
  id: string;
  reference: string;
  vehicleId: string;
  scheduleId?: string;
  workshopId?: string;
  incidentId?: string;
  status: WorkOrderStatus;
  priority: Priority;
  category: string;
  title: string;
  problem?: string;
  diagnosis?: string;
  workPerformed?: string;
  technician?: string;
  scheduledStart?: number;
  expectedCompletion?: number;
  actualStart?: number;
  actualCompletion?: number;
  downtimeHours?: number;
  labourHours: number;
  labourRate: number;
  labourCost: number;
  partsCost: number;
  totalCost: number;
  estimatedCost: number;
  odometerKm: number;
  parts: WorkOrderPart[];
  notes?: string;
  createdAt: number;
  cancelledReason?: string;
}

export interface MaintenanceRecord {
  id: string;
  vehicleId: string;
  workOrderId?: string;
  scheduleId?: string;
  category: string;
  serviceDate: string;
  odometerKm: number;
  workPerformed: string;
  partsCost: number;
  labourCost: number;
  totalCost: number;
  downtimeHours: number;
  workshopName?: string;
  technician?: string;
}

export interface Workshop {
  id: string;
  name: string;
  address: string;
  lat: number;
  lon: number;
  contactName: string;
  contactPhone: string;
  dailyCapacity: number;
  openingTime: string;
  closingTime: string;
  services: string[];
  internal: boolean;
  active: boolean;
}

export interface FuelTransaction {
  id: string;
  vehicleId: string;
  driverId?: string;
  occurredAt: number;
  stationName: string;
  fuelType: FuelKind;
  litres: number;
  pricePerLitre: number;
  totalCost: number;
  odometerKm: number;
  distanceSinceLastKm?: number;
  fullTank: boolean;
  reference: string;
}

export interface ChargingSession {
  id: string;
  vehicleId: string;
  driverId?: string;
  startedAt: number;
  endedAt?: number;
  locationName: string;
  energyKwh: number;
  pricePerKwh: number;
  totalCost: number;
  startSocPct: number;
  endSocPct: number;
  odometerKm: number;
}

export interface FleetDocument {
  id: string;
  kind: string;
  name: string;
  entityType: 'vehicle' | 'driver' | 'organization';
  vehicleId?: string;
  driverId?: string;
  issuer: string;
  reference: string;
  issueDate: string;
  expiryDate: string;
  status: DocStatus;
  cost?: number;
  notes?: string;
  lastAlertedDays?: number;
}

export interface Incident {
  id: string;
  reference: string;
  kind: string;
  severity: Severity;
  status: IncidentStatus;
  title: string;
  description?: string;
  occurredAt: number;
  lat?: number;
  lon?: number;
  address?: string;
  vehicleId?: string;
  driverId?: string;
  tripId?: string;
  taskId?: string;
  workOrderId?: string;
  photos: string[];
  witnesses: { name: string; contact: string }[];
  estimatedCost?: number;
  reportedBy?: string;
  resolvedAt?: number;
  resolutionNote?: string;
}

export interface Inspection {
  id: string;
  driverId: string;
  vehicleId: string;
  performedAt: number;
  result: 'ready' | 'issue_found';
  items: Record<string, boolean>;
  notes?: string;
  incidentId?: string;
  workOrderId?: string;
}

export interface CostRecord {
  id: string;
  vehicleId?: string;
  category: string;
  incurredOn: string;
  amount: number;
  description: string;
  sourceType?: string;
  sourceId?: string;
  odometerKm?: number;
}

export interface Recommendation {
  id: string;
  kind: string;
  source: string;
  title: string;
  situation: string;
  evidence: string[];
  recommendation: string;
  expectedImpact: string;
  severity: Severity;
  status: 'pending' | 'applied' | 'dismissed';
  action?: Record<string, unknown>;
  entityType?: string;
  entityId?: string;
  createdAt: number;
  appliedAt?: number;
  appliedBy?: string;
  dismissedAt?: number;
  resultNote?: string;
}

export interface TimelineEntry {
  id: string;
  entityType: string;
  entityId: string;
  occurredAt: number;
  actorType: 'system' | 'user' | 'driver';
  actorName: string;
  action: string;
  description: string;
  relatedType?: string;
  relatedId?: string;
}

export interface AuditEntry {
  id: string;
  at: number;
  actorName: string;
  actorRole: string;
  action: string;
  entityType?: string;
  entityLabel?: string;
  summary: string;
  before?: Record<string, unknown>;
  after?: Record<string, unknown>;
}

export interface Notification {
  id: string;
  userId: string;
  kind: string;
  title: string;
  body?: string;
  link?: string;
  entityType?: string;
  entityId?: string;
  createdAt: number;
  readAt?: number;
}

export interface Disruption {
  id: string;
  kind: 'closure' | 'weather' | 'congestion';
  /** The real OSM segment affected, so the map highlights the road itself. */
  geometry?: [number, number][];
  title: string;
  description: string;
  severity: Severity;
  lat: number;
  lon: number;
  radiusM: number;
  street?: string;
  delayMinutes: number;
  active: boolean;
}

export interface WeatherCell {
  id: string;
  lat: number;
  lon: number;
  condition: 'clear' | 'rain' | 'sleet' | 'snow' | 'fog' | 'storm';
  temperatureC: number;
  windKph: number;
  precipitationMm: number;
  visibilityM: number;
  severity: 'none' | 'low' | 'medium' | 'high';
  radiusM: number;
  observedAt: number;
}

export interface SavedView {
  id: string;
  name: string;
  surface: string;
  filters: Record<string, unknown>;
  shared: boolean;
}
