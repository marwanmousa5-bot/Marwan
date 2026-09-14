// The FleetBeat world: all state, plus a tiny subscribe/emit store the React
// layer binds to. Mutations go through actions.ts so every change also writes
// a timeline entry and an audit record, exactly as the server build does.

import type {
  Alert, AlertRule, AuditEntry, BadgeAward, ChargingSession, CostRecord, Customer,
  Device, Disruption, Driver, DriverEvent, FleetDocument, FuelTransaction, Geofence,
  Incident, Inspection, MaintenanceRecord, MaintenanceSchedule, Notification, Org,
  Place, PointTransaction, Recommendation, Route, SavedView, Task, TimelineEntry,
  Trip, User, Vehicle, WeatherCell, WorkOrder, Workshop,
} from './types';
import type { StreetGraph } from './router';

export interface State {
  org: Org;
  users: User[];
  currentUserId: string;
  vehicles: Vehicle[];
  drivers: Driver[];
  devices: Device[];
  places: Place[];
  customers: Customer[];
  geofences: Geofence[];
  geofenceInside: Record<string, boolean>;   // `${fenceId}:${vehicleId}`
  workshops: Workshop[];
  routes: Route[];
  trips: Trip[];
  tasks: Task[];
  alertRules: AlertRule[];
  alerts: Alert[];
  driverEvents: DriverEvent[];
  pointTransactions: PointTransaction[];
  badges: BadgeAward[];
  schedules: MaintenanceSchedule[];
  workOrders: WorkOrder[];
  maintenanceRecords: MaintenanceRecord[];
  fuel: FuelTransaction[];
  charging: ChargingSession[];
  documents: FleetDocument[];
  incidents: Incident[];
  inspections: Inspection[];
  costs: CostRecord[];
  recommendations: Recommendation[];
  timeline: TimelineEntry[];
  audit: AuditEntry[];
  notifications: Notification[];
  disruptions: Disruption[];
  weather: WeatherCell[];
  savedViews: SavedView[];
  now: number;
  simRunning: boolean;
  simSpeed: number;
  ticks: number;
  connection: 'live' | 'reconnecting' | 'paused';
  lastEventAt: number;
  counters: Record<string, number>;
}

export type Listener = () => void;

export class Store {
  state: State;
  graph: StreetGraph;
  /**
   * Bumped on every state change. State lives in mutable arrays, so array identity
   * never changes and `useMemo` cannot see a write; read models key off this instead.
   */
  revision = 0;
  private listeners = new Set<Listener>();
  private frame: number | null = null;

  constructor(state: State, graph: StreetGraph) {
    this.state = state;
    this.graph = graph;
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /** Coalesce notifications to one per animation frame - GPS ticks are frequent. */
  emit() {
    this.revision++;
    if (this.frame !== null) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = null;
      this.listeners.forEach((fn) => fn());
    });
  }

  emitNow() {
    this.revision++;
    if (this.frame !== null) {
      cancelAnimationFrame(this.frame);
      this.frame = null;
    }
    this.listeners.forEach((fn) => fn());
  }

  id(prefix: string): string {
    const n = (this.state.counters[prefix] ?? 0) + 1;
    this.state.counters[prefix] = n;
    return `${prefix}_${n.toString(36).padStart(4, '0')}`;
  }

  seq(prefix: string): number {
    const n = (this.state.counters[`seq_${prefix}`] ?? 0) + 1;
    this.state.counters[`seq_${prefix}`] = n;
    return n;
  }

  get me(): User {
    return this.state.users.find((u) => u.id === this.state.currentUserId)!;
  }

  vehicle(id?: string): Vehicle | undefined {
    return id ? this.state.vehicles.find((v) => v.id === id) : undefined;
  }
  driver(id?: string): Driver | undefined {
    return id ? this.state.drivers.find((d) => d.id === id) : undefined;
  }
  task(id?: string): Task | undefined {
    return id ? this.state.tasks.find((t) => t.id === id) : undefined;
  }
  route(id?: string): Route | undefined {
    return id ? this.state.routes.find((r) => r.id === id) : undefined;
  }
  trip(id?: string): Trip | undefined {
    return id ? this.state.trips.find((t) => t.id === id) : undefined;
  }
  alert(id?: string): Alert | undefined {
    return id ? this.state.alerts.find((a) => a.id === id) : undefined;
  }
  workOrder(id?: string): WorkOrder | undefined {
    return id ? this.state.workOrders.find((w) => w.id === id) : undefined;
  }
  place(id?: string): Place | undefined {
    return id ? this.state.places.find((p) => p.id === id) : undefined;
  }
  customer(id?: string): Customer | undefined {
    return id ? this.state.customers.find((c) => c.id === id) : undefined;
  }
  incident(id?: string): Incident | undefined {
    return id ? this.state.incidents.find((i) => i.id === id) : undefined;
  }
  workshop(id?: string): Workshop | undefined {
    return id ? this.state.workshops.find((w) => w.id === id) : undefined;
  }
  user(id?: string): User | undefined {
    return id ? this.state.users.find((u) => u.id === id) : undefined;
  }

  /** Append-only activity entry for an entity (spec 12). */
  timeline(entry: {
    entityType: string; entityId: string; action: string; description: string;
    actorType?: 'system' | 'user' | 'driver'; actorName?: string;
    relatedType?: string; relatedId?: string; at?: number;
  }) {
    this.state.timeline.push({
      id: this.id('tl'),
      entityType: entry.entityType,
      entityId: entry.entityId,
      occurredAt: entry.at ?? this.state.now,
      actorType: entry.actorType ?? 'system',
      actorName: entry.actorName ?? 'System',
      action: entry.action,
      description: entry.description,
      relatedType: entry.relatedType,
      relatedId: entry.relatedId,
    });
    if (this.state.timeline.length > 6000) this.state.timeline.splice(0, 1500);
  }

  /** Append-only audit record (spec 33). */
  audit(entry: {
    action: string; summary: string; entityType?: string; entityLabel?: string;
    before?: Record<string, unknown>; after?: Record<string, unknown>;
    actorName?: string; actorRole?: string; at?: number;
  }) {
    const me = this.me;
    this.state.audit.unshift({
      id: this.id('au'),
      at: entry.at ?? this.state.now,
      actorName: entry.actorName ?? me.fullName,
      actorRole: entry.actorRole ?? me.role,
      action: entry.action,
      entityType: entry.entityType,
      entityLabel: entry.entityLabel,
      summary: entry.summary,
      before: entry.before,
      after: entry.after,
    });
    if (this.state.audit.length > 3000) this.state.audit.length = 2000;
  }

  notify(userId: string, n: {
    kind: string; title: string; body?: string; link?: string;
    entityType?: string; entityId?: string;
  }) {
    this.state.notifications.unshift({
      id: this.id('nt'), userId, createdAt: this.state.now, ...n,
    });
    if (this.state.notifications.length > 400) this.state.notifications.length = 300;
  }

  timelineFor(entityType: string, entityId: string): TimelineEntry[] {
    return this.state.timeline
      .filter((e) => e.entityType === entityType && e.entityId === entityId)
      .sort((a, b) => b.occurredAt - a.occurredAt);
  }
}

export let store: Store;

export function setStore(s: Store) {
  store = s;
}
