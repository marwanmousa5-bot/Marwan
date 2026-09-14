// Fixed reference data for the demo tenant: the alert rule catalogue, the
// maintenance templates, the vehicle and crew roster. Real Helsinki businesses
// supply the customer sites; they are read from the OSM extract at boot.

import type { AlertRule, OrgSettings } from './types';

export const DEFAULT_SETTINGS: OrgSettings = {
  currency: 'EUR',
  fuelPricePerLitre: 1.82,
  energyPricePerKwh: 0.17,
  co2PerLitreDiesel: 2.68,
  co2PerLitrePetrol: 2.31,
  co2PerKwh: 0.061,
  showLeaderboardToDrivers: true,
  driverPointsStart: 100,
  driverPoints: {
    overspeed: -5, harsh_braking: -3, harsh_acceleration: -3, harsh_cornering: -2,
    geofence_breach: -8, route_deviation: -2, idling: -1,
    clean_streak: 10, eco_driving: 5, improvement: 8,
  },
  safetyWeights: {
    overspeed: 6, harsh_braking: 4, harsh_acceleration: 3.5,
    harsh_cornering: 3, route_deviation: 2, incident: 12,
  },
  gpsLiveThresholdS: 45,
  gpsStaleThresholdS: 300,
  documentAlertDays: [30, 14, 7, 1],
  maintenanceDueSoonKm: 500,
  maintenanceDueSoonDays: 14,
  alertEscalationMinutes: [5, 10],
  slaAtRiskMinutes: 15,
  maintenanceHealthWeights: {
    overdue: 25, critical: 30, due: 10, due_soon: 4,
    open_work_order: 6, repeat_failure: 15,
  },
  evCandidateDailyKm: 180,
  labourRate: 78,
};

type RuleSeed = Omit<AlertRule, 'id' | 'vehicleIds' | 'driverIds' | 'notifyRoles'
  | 'notifyChannels' | 'escalationMinutes' | 'active' | 'system'>;

export const RULE_CATALOG: RuleSeed[] = [
  { code: 'overspeed', name: 'Overspeed', category: 'vehicle', severity: 'high',
    description: 'Vehicle exceeded the posted limit for a sustained period.',
    metric: 'speed', operator: '>', threshold: 15, thresholdUnit: 'km/h over limit',
    durationS: 20, cooldownS: 300, dedupeWindowS: 180,
    recommendedAction: 'Contact the driver and log a coaching note.' },
  { code: 'harsh_braking', name: 'Harsh braking', category: 'driver', severity: 'medium',
    description: 'Rapid deceleration detected.', metric: 'deceleration', operator: '>',
    threshold: 3.5, thresholdUnit: 'm/s²', durationS: 0, cooldownS: 180, dedupeWindowS: 300,
    recommendedAction: "Review the driver's braking trend this week." },
  { code: 'harsh_acceleration', name: 'Harsh acceleration', category: 'driver', severity: 'low',
    description: 'Rapid acceleration detected.', metric: 'acceleration', operator: '>',
    threshold: 3.2, thresholdUnit: 'm/s²', durationS: 0, cooldownS: 180, dedupeWindowS: 300 },
  { code: 'harsh_cornering', name: 'Harsh cornering', category: 'driver', severity: 'low',
    description: 'High lateral force through a turn.', metric: 'lateral_g', operator: '>',
    threshold: 0.45, thresholdUnit: 'g', durationS: 0, cooldownS: 180, dedupeWindowS: 300 },
  { code: 'excessive_idling', name: 'Excessive idling', category: 'vehicle', severity: 'low',
    description: 'Engine idling beyond the permitted window.', metric: 'idle_minutes',
    operator: '>', threshold: 15, thresholdUnit: 'min', durationS: 0, cooldownS: 900,
    dedupeWindowS: 900,
    recommendedAction: 'Ask the driver to switch off the engine while waiting.' },
  { code: 'vehicle_offline', name: 'Vehicle offline', category: 'vehicle', severity: 'medium',
    description: 'No GPS data received for an extended period.', metric: 'gps_age',
    operator: '>', threshold: 600, thresholdUnit: 's', durationS: 0, cooldownS: 1800,
    dedupeWindowS: 1800,
    recommendedAction: 'Check the telematics device and vehicle power.' },
  { code: 'gps_signal_loss', name: 'GPS signal degraded', category: 'vehicle', severity: 'low',
    description: 'Satellite fix quality dropped below the usable threshold.',
    metric: 'satellites', operator: '<', threshold: 4, thresholdUnit: 'sats',
    durationS: 0, cooldownS: 900, dedupeWindowS: 900 },
  { code: 'unauthorized_movement', name: 'Unauthorised movement', category: 'security',
    severity: 'critical',
    description: 'Vehicle moved with no driver assigned or accepted task.',
    metric: 'movement_without_driver', operator: '=', threshold: 1, durationS: 0,
    cooldownS: 600, dedupeWindowS: 600,
    recommendedAction: 'Verify with the depot, then escalate to security.' },
  { code: 'route_deviation', name: 'Route deviation', category: 'route', severity: 'medium',
    description: 'Vehicle left its planned route corridor.', metric: 'deviation',
    operator: '>', threshold: 250, thresholdUnit: 'm', durationS: 60, cooldownS: 600,
    dedupeWindowS: 600,
    recommendedAction: 'Confirm the reason with the driver; re-route if needed.' },
  { code: 'task_delayed', name: 'Delayed arrival', category: 'route', severity: 'high',
    description: 'Projected arrival is later than the committed window.',
    metric: 'eta_overrun', operator: '>', threshold: 10, thresholdUnit: 'min',
    durationS: 0, cooldownS: 900, dedupeWindowS: 900,
    recommendedAction: 'Notify the customer and consider reassignment.' },
  { code: 'sla_breach_risk', name: 'SLA at risk', category: 'route', severity: 'high',
    description: 'Task SLA will breach unless action is taken.',
    metric: 'sla_remaining', operator: '<', threshold: 15, thresholdUnit: 'min',
    durationS: 0, cooldownS: 900, dedupeWindowS: 900,
    recommendedAction: 'Reprioritise or reassign the task.' },
  { code: 'missed_stop', name: 'Missed stop', category: 'route', severity: 'medium',
    description: 'Vehicle passed a planned stop without recording an arrival.',
    metric: 'stop_skipped', operator: '=', threshold: 1, durationS: 0,
    cooldownS: 600, dedupeWindowS: 600 },
  { code: 'geofence_enter', name: 'Geofence entry', category: 'geofence', severity: 'low',
    description: 'Vehicle entered a monitored zone.', metric: 'geofence_enter',
    operator: '=', threshold: 1, durationS: 0, cooldownS: 60, dedupeWindowS: 60 },
  { code: 'geofence_exit', name: 'Geofence exit', category: 'geofence', severity: 'low',
    description: 'Vehicle left a monitored zone.', metric: 'geofence_exit',
    operator: '=', threshold: 1, durationS: 0, cooldownS: 60, dedupeWindowS: 60 },
  { code: 'geofence_unauthorized', name: 'Restricted zone breach', category: 'geofence',
    severity: 'critical', description: 'Vehicle entered a zone it may not enter.',
    metric: 'restricted_zone', operator: '=', threshold: 1, durationS: 0,
    cooldownS: 300, dedupeWindowS: 300,
    recommendedAction: 'Contact the driver immediately and record the breach.' },
  { code: 'maintenance_due_soon', name: 'Service due soon', category: 'maintenance',
    severity: 'low', description: 'Preventive service threshold is approaching.',
    metric: 'km_to_service', operator: '<', threshold: 500, thresholdUnit: 'km',
    durationS: 0, cooldownS: 86400, dedupeWindowS: 86400,
    recommendedAction: 'Book a workshop slot.' },
  { code: 'maintenance_due', name: 'Service due', category: 'maintenance', severity: 'medium',
    description: 'Preventive service threshold reached.', metric: 'km_to_service',
    operator: '<=', threshold: 50, thresholdUnit: 'km', durationS: 0,
    cooldownS: 86400, dedupeWindowS: 86400,
    recommendedAction: 'Schedule the work order now.' },
  { code: 'maintenance_overdue', name: 'Service overdue', category: 'maintenance',
    severity: 'high', description: 'Preventive service is past its threshold.',
    metric: 'km_to_service', operator: '<', threshold: 0, thresholdUnit: 'km',
    durationS: 0, cooldownS: 86400, dedupeWindowS: 86400,
    recommendedAction: 'Take the vehicle off rotation and service it.' },
  { code: 'maintenance_critical', name: 'Critical maintenance', category: 'maintenance',
    severity: 'critical', description: 'Service is severely overdue — continued use is a risk.',
    metric: 'km_to_service', operator: '<', threshold: -1000, thresholdUnit: 'km',
    durationS: 0, cooldownS: 86400, dedupeWindowS: 86400,
    recommendedAction: 'Ground the vehicle until serviced.' },
  { code: 'work_order_overdue', name: 'Work order overdue', category: 'maintenance',
    severity: 'medium', description: 'Work order passed its expected completion time.',
    metric: 'wo_overrun', operator: '>', threshold: 2, thresholdUnit: 'h', durationS: 0,
    cooldownS: 7200, dedupeWindowS: 7200,
    recommendedAction: 'Chase the workshop for an updated ETA.' },
  { code: 'document_expiring', name: 'Document expiring', category: 'compliance',
    severity: 'medium', description: 'A compliance document is approaching expiry.',
    metric: 'days_to_expiry', operator: '<=', threshold: 30, thresholdUnit: 'days',
    durationS: 0, cooldownS: 86400, dedupeWindowS: 86400,
    recommendedAction: 'Renew the document before it lapses.' },
  { code: 'document_expired', name: 'Document expired', category: 'compliance',
    severity: 'critical', description: 'A compliance document has expired.',
    metric: 'days_to_expiry', operator: '<', threshold: 0, thresholdUnit: 'days',
    durationS: 0, cooldownS: 86400, dedupeWindowS: 86400,
    recommendedAction: 'Remove the vehicle or driver from service.' },
  { code: 'license_expiring', name: 'Driver licence expiring', category: 'compliance',
    severity: 'medium', description: 'A driver licence is approaching expiry.',
    metric: 'days_to_expiry', operator: '<=', threshold: 30, thresholdUnit: 'days',
    durationS: 0, cooldownS: 86400, dedupeWindowS: 86400 },
  { code: 'fatigue_risk', name: 'Fatigue risk', category: 'driver', severity: 'high',
    description: 'Driver exceeded the safe continuous duty window.', metric: 'duty_hours',
    operator: '>', threshold: 9, thresholdUnit: 'h', durationS: 0, cooldownS: 3600,
    dedupeWindowS: 3600,
    recommendedAction: 'Require a rest break before the next task.' },
  { code: 'suspicious_login', name: 'Suspicious sign-in', category: 'security',
    severity: 'high', description: 'Repeated failed sign-ins, or a new device.',
    metric: 'failed_logins', operator: '>=', threshold: 5, durationS: 0,
    cooldownS: 900, dedupeWindowS: 900,
    recommendedAction: 'Verify with the user and reset credentials.' },
];

export interface VehicleSeed {
  name: string; plate: string; type: string; make: string; model: string;
  year: number; fuel: string; colour: string; consumption?: number;
  batteryKwh?: number; tank?: number; value: number; residual: number;
}

// Finnish plates use the ABC-123 format.
export const VEHICLE_SEEDS: VehicleSeed[] = [
  { name: 'KL-01', plate: 'JLM-418', type: 'van', make: 'Mercedes-Benz', model: 'Sprinter 315',
    year: 2021, fuel: 'diesel', colour: 'White', consumption: 9.4, tank: 71, value: 46500, residual: 14000 },
  { name: 'KL-02', plate: 'KRV-207', type: 'van', make: 'Volkswagen', model: 'Crafter 35',
    year: 2020, fuel: 'diesel', colour: 'White', consumption: 9.8, tank: 75, value: 43800, residual: 12500 },
  { name: 'KL-03', plate: 'PNT-663', type: 'van', make: 'Ford', model: 'Transit Custom',
    year: 2022, fuel: 'diesel', colour: 'Silver', consumption: 8.1, tank: 70, value: 39900, residual: 15000 },
  { name: 'KL-04', plate: 'ASH-921', type: 'ev_van', make: 'Nissan', model: 'e-NV200',
    year: 2022, fuel: 'electric', colour: 'White', batteryKwh: 40, value: 38000, residual: 12000 },
  { name: 'KL-05', plate: 'TUG-154', type: 'refrigerated_van', make: 'Renault', model: 'Master Frigo',
    year: 2019, fuel: 'diesel', colour: 'White', consumption: 11.6, tank: 80, value: 52000, residual: 11000 },
  { name: 'KL-06', plate: 'VMO-538', type: 'van', make: 'Toyota', model: 'Proace',
    year: 2023, fuel: 'diesel', colour: 'Grey', consumption: 7.6, tank: 69, value: 41200, residual: 19000 },
  { name: 'KL-07', plate: 'HYR-072', type: 'van', make: 'Mercedes-Benz', model: 'Vito 116',
    year: 2020, fuel: 'diesel', colour: 'White', consumption: 8.9, tank: 70, value: 40100, residual: 12000 },
  { name: 'KL-08', plate: 'ELN-346', type: 'ev_van', make: 'Mercedes-Benz', model: 'eVito',
    year: 2023, fuel: 'electric', colour: 'White', batteryKwh: 60, value: 54000, residual: 21000 },
  { name: 'KL-09', plate: 'SIP-889', type: 'van', make: 'Fiat', model: 'Ducato 35',
    year: 2018, fuel: 'diesel', colour: 'White', consumption: 10.7, tank: 90, value: 35600, residual: 7000 },
  { name: 'KL-10', plate: 'ORM-215', type: 'truck', make: 'Volvo', model: 'FL 42',
    year: 2019, fuel: 'diesel', colour: 'Blue', consumption: 19.5, tank: 150, value: 92000, residual: 26000 },
  { name: 'KL-11', plate: 'NUT-604', type: 'van', make: 'Peugeot', model: 'Expert',
    year: 2021, fuel: 'diesel', colour: 'White', consumption: 8.3, tank: 69, value: 37800, residual: 13500 },
  { name: 'KL-12', plate: 'RAK-437', type: 'van', make: 'Opel', model: 'Vivaro',
    year: 2022, fuel: 'diesel', colour: 'Grey', consumption: 8.0, tank: 69, value: 38400, residual: 16000 },
  { name: 'KL-13', plate: 'LEH-290', type: 'cargo_bike', make: 'Urban Arrow', model: 'Cargo XL',
    year: 2023, fuel: 'electric', colour: 'Coral', batteryKwh: 1.1, value: 8900, residual: 2500 },
  { name: 'KL-14', plate: 'MJV-751', type: 'car', make: 'Škoda', model: 'Octavia Combi',
    year: 2021, fuel: 'hybrid', colour: 'Black', consumption: 5.4, tank: 50, value: 32500, residual: 13000 },
];

export interface DriverSeed { name: string; phone: string; colour: string; }

// A Helsinki logistics crew: Finnish names alongside the city's large
// Estonian, Somali, Iraqi and Russian-speaking workforce.
export const DRIVER_SEEDS: DriverSeed[] = [
  { name: 'Aino Virtanen',      phone: '+358 40 512 6631', colour: '#1E90FF' },
  { name: 'Mikko Järvinen',     phone: '+358 44 208 1174', colour: '#2ECC71' },
  { name: 'Yusuf Abdi',         phone: '+358 45 331 9902', colour: '#F5A623' },
  { name: 'Katri Nieminen',     phone: '+358 50 774 2218', colour: '#9B6BFF' },
  { name: 'Rauno Mäkelä',       phone: '+358 40 663 5507', colour: '#FF6B35' },
  { name: 'Elina Koskinen',     phone: '+358 44 190 8863', colour: '#00B8A9' },
  { name: 'Hassan Al-Rawi',     phone: '+358 46 882 4419', colour: '#E74C3C' },
  { name: 'Tuomas Lehtonen',    phone: '+358 50 245 7730', colour: '#5D7FF0' },
  { name: 'Marek Tamm',         phone: '+358 45 517 3382', colour: '#C86DD7' },
  { name: 'Sanna Heikkilä',     phone: '+358 40 991 2245', colour: '#2FB8D9' },
  { name: 'Dmitri Sokolov',     phone: '+358 44 603 8871', colour: '#8FBF3F' },
  { name: 'Laura Peltonen',     phone: '+358 50 328 6094', colour: '#FF8FA3' },
  { name: 'Omar Haddad',        phone: '+358 46 214 7756', colour: '#F2C14E' },
  { name: 'Veikko Salminen',    phone: '+358 40 457 1128', colour: '#6FCF97' },
];

export interface TemplateSeed {
  name: string; description: string; intervalKm: number; intervalMonths: number;
  items: { category: string; label: string; cost: number; minutes: number }[];
}

export const MAINTENANCE_TEMPLATES: TemplateSeed[] = [
  {
    name: 'Basic service', description: 'Routine oil and inspection interval.',
    intervalKm: 15000, intervalMonths: 12,
    items: [
      { category: 'engine_oil', label: 'Engine oil & filter', cost: 145, minutes: 60 },
      { category: 'air_filter', label: 'Air filter', cost: 48, minutes: 20 },
      { category: 'fluids', label: 'Fluid top-up & check', cost: 32, minutes: 20 },
      { category: 'tires', label: 'Tyre inspection & rotation', cost: 60, minutes: 40 },
    ],
  },
  {
    name: 'Major service', description: 'Full inspection at the long interval.',
    intervalKm: 45000, intervalMonths: 36,
    items: [
      { category: 'engine_oil', label: 'Engine oil & filter', cost: 145, minutes: 60 },
      { category: 'brake_pads', label: 'Brake pads & discs', cost: 380, minutes: 150 },
      { category: 'transmission', label: 'Transmission service', cost: 290, minutes: 120 },
      { category: 'cooling', label: 'Cooling system flush', cost: 165, minutes: 90 },
      { category: 'battery', label: 'Battery test & terminals', cost: 55, minutes: 25 },
    ],
  },
  {
    name: 'Safety inspection', description: 'Statutory roadworthiness preparation.',
    intervalKm: 30000, intervalMonths: 12,
    items: [
      { category: 'brake_inspection', label: 'Brake inspection', cost: 90, minutes: 60 },
      { category: 'suspension', label: 'Suspension check', cost: 110, minutes: 60 },
      { category: 'steering', label: 'Steering check', cost: 85, minutes: 45 },
      { category: 'general_inspection', label: 'Lights, wipers & body', cost: 70, minutes: 40 },
    ],
  },
  {
    name: 'EV service', description: 'High-voltage system and brake care for electric vans.',
    intervalKm: 25000, intervalMonths: 12,
    items: [
      { category: 'battery', label: 'HV battery health check', cost: 210, minutes: 90 },
      { category: 'brake_inspection', label: 'Brake inspection (regen wear)', cost: 90, minutes: 60 },
      { category: 'cooling', label: 'Battery coolant check', cost: 120, minutes: 45 },
      { category: 'tires', label: 'Tyre inspection & rotation', cost: 60, minutes: 40 },
    ],
  },
];

export const PARTS_CATALOG = [
  { name: 'Engine oil 5W-30 (5 L)', sku: 'OIL-5W30-5', cost: 42.5, supplier: 'Würth Suomi' },
  { name: 'Oil filter', sku: 'FLT-OIL-221', cost: 18.9, supplier: 'Würth Suomi' },
  { name: 'Air filter', sku: 'FLT-AIR-118', cost: 31.0, supplier: 'Autotarvike Oy' },
  { name: 'Cabin filter', sku: 'FLT-CAB-084', cost: 24.5, supplier: 'Autotarvike Oy' },
  { name: 'Front brake pad set', sku: 'BRK-PAD-F42', cost: 96.0, supplier: 'Brembo Nordic' },
  { name: 'Rear brake disc (pair)', sku: 'BRK-DSC-R19', cost: 178.0, supplier: 'Brembo Nordic' },
  { name: 'Winter tyre 215/65R16', sku: 'TYR-W21565', cost: 142.0, supplier: 'Vianor' },
  { name: 'Wiper blade set', sku: 'WPR-SET-26', cost: 29.9, supplier: 'Autotarvike Oy' },
  { name: 'AGM battery 95Ah', sku: 'BAT-AGM-95', cost: 189.0, supplier: 'Exide Nordic' },
  { name: 'Coolant G12 (5 L)', sku: 'CLN-G12-5', cost: 38.0, supplier: 'Würth Suomi' },
  { name: 'Serpentine belt', sku: 'BLT-SRP-77', cost: 54.0, supplier: 'Autotarvike Oy' },
  { name: 'Glow plug set', sku: 'GLW-SET-4', cost: 68.0, supplier: 'Bosch Service' },
];

export const TECHNICIANS = [
  'Pekka Rantanen', 'Anna Korhonen', 'Jarkko Laine', 'Sofia Väisänen', 'Ilkka Hakala',
];

export const FAILURE_REASONS = [
  { code: 'customer_unavailable', label: 'Customer unavailable' },
  { code: 'access_issue', label: 'Access issue' },
  { code: 'vehicle_issue', label: 'Vehicle issue' },
  { code: 'wrong_address', label: 'Wrong address' },
  { code: 'customer_refused', label: 'Customer refused' },
  { code: 'safety_issue', label: 'Safety issue' },
  { code: 'other', label: 'Other' },
];

export const INSPECTION_ITEMS = [
  { key: 'tyres', label: 'Tyres & pressure' },
  { key: 'lights', label: 'Lights & indicators' },
  { key: 'brakes', label: 'Brakes' },
  { key: 'mirrors', label: 'Mirrors & glass' },
  { key: 'fluids', label: 'Fluid levels' },
  { key: 'body', label: 'Body damage' },
  { key: 'safety', label: 'Safety equipment' },
];
