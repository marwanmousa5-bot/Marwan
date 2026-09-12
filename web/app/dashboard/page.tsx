"use client";

/**
 * Live Tracking - the landing page for every dashboard user (Section 4b).
 *
 * Layout: collapsible vehicle sidebar, a large live map, a bottom KPI strip
 * and a collapsible alerts drawer. The vehicle list and the map stay in sync
 * in both directions: selecting a row flies the map, clicking a marker
 * selects the row.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";

import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import { useLiveFeed } from "@/lib/useLiveFeed";
import type {
  Alert,
  Geofence,
  RoadClosure,
  LiveKpis,
  LiveSnapshot,
  LiveVehicle,
  Page,
  Poi,
  Task,
  WeatherZone,
} from "@/lib/types";
import type { DrawMode, DrawnGeometry, LayerVisibility } from "@/components/map/FleetMap";
import { CopilotPanel } from "@/components/ai/CopilotPanel";
import { LayerControl } from "@/components/LayerControl";
import { StatusDot, statusLabel } from "@/components/StatusDot";

// MapLibre touches `window` at import time, so it must not be server-rendered.
const FleetMap = dynamic(
  () => import("@/components/map/FleetMap").then((m) => m.FleetMap),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center bg-ink-800 text-sm text-ink-400">
        {strings.common.loading}
      </div>
    ),
  },
);

type Filter = "all" | "moving" | "idle" | "alert" | "not_tracked";

const FILTERS: [Filter, string][] = [
  ["all", strings.live.filters.all],
  ["moving", strings.live.filters.moving],
  ["idle", strings.live.filters.stopped],
  ["alert", strings.live.filters.alert],
  ["not_tracked", strings.live.filters.notTracked],
];

/** Fallback refresh when the socket is unavailable. */
const POLL_INTERVAL_MS = 15_000;

export default function LiveTrackingPage() {
  const { session } = useSession();
  const canDraw = session?.user.role === "org_admin";

  const [vehicles, setVehicles] = useState<LiveVehicle[]>([]);
  const [kpis, setKpis] = useState<LiveKpis | null>(null);
  const [geofences, setGeofences] = useState<Geofence[]>([]);
  const [pois, setPois] = useState<Poi[]>([]);
  const [weatherZones, setWeatherZones] = useState<WeatherZone[]>([]);
  const [taskDestinations, setTaskDestinations] = useState<Task[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [alertsOpen, setAlertsOpen] = useState(true);
  // The right rail carries both the alert feed and the Copilot (Section 4e);
  // they compete for the same attention, so they share one column as tabs.
  const [rail, setRail] = useState<"alerts" | "copilot">("alerts");
  const [drawMode, setDrawMode] = useState<DrawMode>("none");
  const [poiMode, setPoiMode] = useState(false);
  const [closureMode, setClosureMode] = useState(false);
  const [roadClosures, setRoadClosures] = useState<RoadClosure[]>([]);
  const [layers, setLayers] = useState<LayerVisibility>({
    vehicles: true,
    geofences: true,
    pois: true,
    weather: false,
    tasks: true,
    closures: true,
  });

  const loadedOnce = useRef(false);

  const loadSnapshot = useCallback(async () => {
    const snapshot = await api.get<LiveSnapshot>("/live/snapshot");
    setVehicles(snapshot.vehicles);
    setKpis(snapshot.kpis);
  }, []);

  const loadAlerts = useCallback(async () => {
    // Acknowledged alerts are claimed, not finished, so the feed keeps them
    // alongside the unclaimed ones - otherwise acknowledging would look
    // exactly like resolving.
    const page = await api.get<Page<Alert>>(
      "/alerts?status=active&status=acknowledged&limit=30",
    );
    setAlerts(page.items);
  }, []);

  const loadTaskDestinations = useCallback(async () => {
    // Only work still in flight belongs on the live map.
    const open = await Promise.all(
      (["assigned", "accepted", "en_route"] as const).map((status) =>
        api.get<Page<Task>>(`/tasks?status=${status}&limit=100`),
      ),
    );
    setTaskDestinations(open.flatMap((page) => page.items));
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [, , , fences, points, zones, closures] = await Promise.all([
          loadSnapshot(),
          loadAlerts(),
          loadTaskDestinations(),
          api.get<Geofence[]>("/geofences"),
          api.get<Poi[]>("/pois"),
          api.get<WeatherZone[]>("/weather-zones"),
          api.get<RoadClosure[]>("/road-closures"),
        ]);
        if (cancelled) return;
        setGeofences(fences);
        setPois(points);
        setWeatherZones(zones);
        setRoadClosures(closures);
        setError(null);
      } catch {
        if (!cancelled) setError("We could not load your live fleet view.");
      } finally {
        if (!cancelled) {
          setLoading(false);
          loadedOnce.current = true;
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadSnapshot, loadAlerts, loadTaskDestinations]);

  const handleAlert = useCallback((alert: Alert) => {
    setAlerts((current) => [alert, ...current].slice(0, 50));
    setKpis((current) =>
      current ? { ...current, active_alerts: current.active_alerts + 1 } : current,
    );
  }, []);

  const { state: connection } = useLiveFeed(vehicles, setVehicles, {
    enabled: loadedOnce.current || !loading,
    onAlert: handleAlert,
    onTripChange: loadSnapshot,
  });

  // Keep KPI counts honest between socket updates, and act as the fallback
  // refresh whenever the socket is not open.
  useEffect(() => {
    const interval = connection === "open" ? POLL_INTERVAL_MS * 4 : POLL_INTERVAL_MS;
    const timer = setInterval(() => {
      void loadSnapshot().catch(() => undefined);
    }, interval);
    return () => clearInterval(timer);
  }, [connection, loadSnapshot]);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return vehicles.filter((vehicle) => {
      if (filter !== "all" && vehicle.live_status !== filter) return false;
      if (!term) return true;
      return (
        vehicle.name.toLowerCase().includes(term) ||
        vehicle.license_plate.toLowerCase().includes(term) ||
        (vehicle.driver_name ?? "").toLowerCase().includes(term)
      );
    });
  }, [vehicles, filter, search]);

  const selected = vehicles.find((v) => v.id === selectedId) ?? null;

  async function handleDrawComplete(drawn: DrawnGeometry) {
    setDrawMode("none");
    const name = window.prompt("Name this geofence");
    if (!name) return;
    try {
      const created = await api.post<Geofence>("/geofences", {
        name,
        shape: drawn.shape,
        geometry: drawn.geometry,
        trigger: "both",
        color: "#1E90FF",
      });
      setGeofences((current) => [...current, created]);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "We could not save that geofence.",
      );
    }
  }

  async function handleMapClick(lngLat: { lng: number; lat: number }) {
    if (closureMode) {
      setClosureMode(false);
      const label = window.prompt(strings.live.closurePrompt);
      if (!label) return;
      try {
        const created = await api.post<RoadClosure>("/road-closures", {
          label,
          latitude: lngLat.lat,
          longitude: lngLat.lng,
          radius_m: 400,
        });
        setRoadClosures((current) => [created, ...current]);
      } catch (err) {
        setError(
          err instanceof ApiError ? err.message : "We could not flag that closure.",
        );
      }
      return;
    }
    if (!poiMode) return;
    setPoiMode(false);
    const name = window.prompt("Name this point of interest");
    if (!name) return;
    try {
      const created = await api.post<Poi>("/pois", {
        name,
        category: "custom",
        latitude: lngLat.lat,
        longitude: lngLat.lng,
      });
      setPois((current) => [...current, created]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We could not save that POI.");
    }
  }

  async function resolveAlert(alertId: string) {
    try {
      await api.post(`/alerts/${alertId}/resolve`);
      setAlerts((current) => current.filter((a) => a.id !== alertId));
      await loadSnapshot();
    } catch {
      /* the feed will correct itself on the next refresh */
    }
  }

  /** Seen, but still open - the alert stays in the feed, visibly claimed. */
  async function acknowledgeAlert(alertId: string) {
    try {
      const updated = await api.post<Alert>(`/alerts/${alertId}/acknowledge`);
      setAlerts((current) =>
        current.map((a) => (a.id === updated.id ? updated : a)),
      );
    } catch {
      /* the feed will correct itself on the next refresh */
    }
  }

  /** Roadworks end. A closure nobody can lift keeps proposing reroutes. */
  async function liftClosure(closureId: string) {
    try {
      await api.patch<RoadClosure>(`/road-closures/${closureId}`, {
        is_active: false,
      });
      setRoadClosures((current) => current.filter((c) => c.id !== closureId));
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "We could not lift that closure.",
      );
    }
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col gap-0 -m-4 md:-m-6">
      <div className="flex min-h-0 flex-1">
        {/* --- vehicle sidebar --- */}
        <aside
          className={`flex shrink-0 flex-col border-r border-ink-700 bg-ink-800/60 transition-all ${
            sidebarOpen ? "w-72" : "w-12"
          }`}
        >
          <div className="flex items-center justify-between border-b border-ink-700 px-3 py-2.5">
            {sidebarOpen && (
              <span className="text-sm font-semibold text-white">
                {strings.dashboard.vehiclesTitle}
                <span className="fb-numeric ml-2 text-xs font-normal text-ink-400">
                  {filtered.length}/{vehicles.length}
                </span>
              </span>
            )}
            <button
              onClick={() => setSidebarOpen((open) => !open)}
              aria-label={sidebarOpen ? "Collapse vehicle list" : "Expand vehicle list"}
              className="rounded p-1 text-ink-300 hover:bg-ink-700 hover:text-white"
            >
              {sidebarOpen ? "«" : "»"}
            </button>
          </div>

          {sidebarOpen && (
            <>
              <div className="space-y-2 border-b border-ink-700 p-3">
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={strings.live.searchPlaceholder}
                  aria-label={strings.live.searchPlaceholder}
                  className="fb-input !py-1.5 text-xs"
                />
                <div className="flex flex-wrap gap-1">
                  {FILTERS.map(([value, label]) => (
                    <button
                      key={value}
                      onClick={() => setFilter(value)}
                      className={`rounded-full px-2.5 py-1 text-[11px] transition ${
                        filter === value
                          ? "bg-electric text-white"
                          : "bg-ink-700 text-ink-300 hover:bg-ink-600"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <ul className="min-h-0 flex-1 divide-y divide-ink-700/60 overflow-y-auto">
                {loading ? (
                  <li className="px-3 py-4 text-xs text-ink-400">
                    {strings.common.loading}
                  </li>
                ) : filtered.length === 0 ? (
                  <li className="px-3 py-4 text-xs text-ink-400">
                    {strings.common.empty}
                  </li>
                ) : (
                  filtered.map((vehicle) => (
                    <li key={vehicle.id}>
                      <button
                        onClick={() =>
                          setSelectedId(vehicle.id === selectedId ? null : vehicle.id)
                        }
                        aria-current={vehicle.id === selectedId ? "true" : undefined}
                        className={`flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition ${
                          vehicle.id === selectedId
                            ? "bg-electric/10"
                            : "hover:bg-ink-700/50"
                        }`}
                      >
                        <span className="mt-1">
                          <StatusDot status={vehicle.live_status} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-xs font-medium text-ink-50">
                            {vehicle.name}
                          </span>
                          <span className="block truncate text-[11px] text-ink-400">
                            {vehicle.license_plate}
                            {vehicle.driver_name && ` · ${vehicle.driver_name}`}
                          </span>
                          <span className="fb-numeric mt-0.5 block text-[11px] text-ink-300">
                            {vehicle.live_status === "not_tracked"
                              ? strings.live.notTrackedNudge
                              : vehicle.live_status === "moving"
                                ? `${Math.round(vehicle.speed_kph ?? 0)} km/h`
                                : vehicle.stopped_since
                                  ? `${strings.live.stoppedSince} ${timeOnly(vehicle.stopped_since)}`
                                  : statusLabel(vehicle.live_status)}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))
                )}
              </ul>
            </>
          )}
        </aside>

        {/* --- map --- */}
        <div className="relative min-w-0 flex-1">
          <FleetMap
            vehicles={vehicles}
            geofences={geofences}
            pois={pois}
            weatherZones={weatherZones}
            taskDestinations={taskDestinations}
            roadClosures={roadClosures}
            layers={layers}
            selectedVehicleId={selectedId}
            onSelectVehicle={setSelectedId}
            drawMode={drawMode}
            onDrawComplete={handleDrawComplete}
            onMapClick={handleMapClick}
          />

          <div className="absolute left-3 top-3 flex flex-col gap-2">
            <LayerControl layers={layers} onChange={setLayers} />
            {canDraw && (
              <div className="rounded-lg border border-ink-600 bg-ink-800/95 p-3 shadow-lg backdrop-blur">
                <p className="fb-label mb-2">{strings.live.drawGeofence}</p>
                <div className="flex gap-1.5">
                  {(["polygon", "circle"] as const).map((mode) => (
                    <button
                      key={mode}
                      onClick={() =>
                        setDrawMode((current) => (current === mode ? "none" : mode))
                      }
                      className={`rounded px-2 py-1 text-[11px] transition ${
                        drawMode === mode
                          ? "bg-electric text-white"
                          : "bg-ink-700 text-ink-200 hover:bg-ink-600"
                      }`}
                    >
                      {mode === "polygon"
                        ? strings.live.drawPolygon
                        : strings.live.drawCircle}
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => {
                    setDrawMode("none");
                    setClosureMode(false);
                    setPoiMode((on) => !on);
                  }}
                  className={`mt-2 w-full rounded px-2 py-1 text-[11px] transition ${
                    poiMode
                      ? "bg-electric text-white"
                      : "bg-ink-700 text-ink-200 hover:bg-ink-600"
                  }`}
                >
                  {poiMode ? "Click the map…" : strings.live.addPoi}
                </button>
                {/* Coral, not electric: a closure is a live disruption, and it
                    is the one thing here that feeds auto-rerouting. */}
                <button
                  onClick={() => {
                    setDrawMode("none");
                    setPoiMode(false);
                    setClosureMode((on) => !on);
                  }}
                  className={`mt-1.5 w-full rounded px-2 py-1 text-[11px] transition ${
                    closureMode
                      ? "bg-coral text-ink-900"
                      : "bg-ink-700 text-ink-200 hover:bg-ink-600"
                  }`}
                >
                  {closureMode ? "Click the map…" : strings.live.flagClosure}
                </button>
              </div>
            )}

            {roadClosures.length > 0 && (
              <div className="w-52 rounded-lg border border-ink-600 bg-ink-800/95 p-3 shadow-lg backdrop-blur">
                <p className="fb-label mb-2">{strings.live.layerClosures}</p>
                <ul className="space-y-1.5">
                  {roadClosures.map((closure) => (
                    <li
                      key={closure.id}
                      className="flex items-start justify-between gap-2"
                    >
                      <span className="min-w-0 flex-1 truncate text-[11px] text-ink-200">
                        {closure.label}
                      </span>
                      {canDraw && (
                        <button
                          onClick={() => liftClosure(closure.id)}
                          className="shrink-0 text-[10px] text-coral hover:text-coral/80"
                        >
                          {strings.live.liftClosure}
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="absolute right-3 top-3 flex items-center gap-2 rounded-full border border-ink-600 bg-ink-800/95 px-3 py-1.5 text-[11px] backdrop-blur">
            <span
              className={`h-2 w-2 rounded-full ${
                connection === "open"
                  ? "bg-success animate-heartbeat"
                  : connection === "connecting"
                    ? "bg-warning"
                    : "bg-ink-400"
              }`}
            />
            <span className="text-ink-200">
              {connection === "open"
                ? strings.live.connectionLive
                : connection === "connecting"
                  ? strings.live.connectionReconnecting
                  : strings.live.connectionOffline}
            </span>
          </div>

          {selected && (
            <div className="absolute bottom-3 left-3 w-72 rounded-lg border border-ink-600 bg-ink-800/95 p-4 shadow-xl backdrop-blur">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-white">
                    {selected.name}
                  </p>
                  <p className="text-xs text-ink-400">{selected.license_plate}</p>
                </div>
                <button
                  onClick={() => setSelectedId(null)}
                  aria-label="Close vehicle details"
                  className="rounded p-1 text-ink-400 hover:bg-ink-700 hover:text-white"
                >
                  ×
                </button>
              </div>
              <dl className="mt-3 space-y-1.5 text-xs">
                <Row label="Status" value={statusLabel(selected.live_status)} />
                <Row label="Driver" value={selected.driver_name ?? "Unassigned"} />
                <Row
                  label="Speed"
                  value={
                    selected.is_tracked
                      ? `${Math.round(selected.speed_kph ?? 0)} km/h`
                      : "—"
                  }
                />
                <Row
                  label={strings.live.lastSeen}
                  value={
                    selected.last_position_at
                      ? new Date(selected.last_position_at).toLocaleTimeString()
                      : "Never"
                  }
                />
                <Row
                  label="GPS device"
                  value={selected.device_serial ?? strings.dashboard.notTracked}
                />
              </dl>
              {!selected.is_tracked && (
                <p className="mt-3 rounded border border-ink-600 px-2 py-1.5 text-[11px] leading-relaxed text-ink-400">
                  {strings.live.noDevice}
                </p>
              )}
              <Link
                href={`/dashboard/history?vehicle=${selected.id}`}
                className="fb-button-ghost mt-3 w-full !py-1.5 text-xs"
              >
                View trip history
              </Link>
            </div>
          )}
        </div>

        {/* --- alerts drawer --- */}
        <aside
          className={`flex shrink-0 flex-col border-l border-ink-700 bg-ink-800/60 transition-all ${
            alertsOpen ? "w-80" : "w-12"
          }`}
        >
          <div className="flex items-center justify-between border-b border-ink-700 px-3 py-2.5">
            <button
              onClick={() => setAlertsOpen((open) => !open)}
              aria-label={alertsOpen ? "Collapse right panel" : "Expand right panel"}
              className="rounded p-1 text-ink-300 hover:bg-ink-700 hover:text-white"
            >
              {alertsOpen ? "»" : "«"}
            </button>
            {alertsOpen && (
              <div role="tablist" className="flex gap-1">
                <button
                  role="tab"
                  aria-selected={rail === "alerts"}
                  onClick={() => setRail("alerts")}
                  className={`flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium transition ${
                    rail === "alerts"
                      ? "bg-ink-700 text-white"
                      : "text-ink-400 hover:text-ink-200"
                  }`}
                >
                  {strings.live.alertsFeed}
                  {alerts.length > 0 && (
                    <span className="fb-badge bg-coral/15 text-coral">
                      {alerts.length}
                    </span>
                  )}
                </button>
                <button
                  role="tab"
                  aria-selected={rail === "copilot"}
                  onClick={() => setRail("copilot")}
                  className={`rounded px-2 py-1 text-xs font-medium transition ${
                    rail === "copilot"
                      ? "bg-ink-700 text-white"
                      : "text-ink-400 hover:text-ink-200"
                  }`}
                >
                  {strings.copilot.title}
                </button>
              </div>
            )}
          </div>

          {alertsOpen && rail === "copilot" && (
            <CopilotPanel onFocusVehicle={(id) => setSelectedId(id)} />
          )}

          {alertsOpen && rail === "alerts" && (
            <ul className="min-h-0 flex-1 divide-y divide-ink-700/60 overflow-y-auto">
              {alerts.length === 0 ? (
                <li className="px-3 py-4 text-xs text-ink-400">
                  {strings.live.noAlerts}
                </li>
              ) : (
                alerts.map((alert) => (
                  <li key={alert.id} className="px-3 py-3">
                    <div className="flex items-start gap-2">
                      <span
                        className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                          alert.severity === "critical"
                            ? "bg-danger"
                            : alert.severity === "warning"
                              ? "bg-warning"
                              : "bg-electric"
                        }`}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-medium text-ink-50">
                          {alert.title}
                          {alert.status === "acknowledged" && (
                            <span className="fb-badge ml-2 bg-ink-700 text-ink-300">
                              {strings.live.acknowledged}
                            </span>
                          )}
                        </p>
                        <p className="mt-0.5 text-[11px] leading-relaxed text-ink-400">
                          {alert.message}
                        </p>
                        <div className="mt-1.5 flex items-center gap-3">
                          <span className="text-[10px] text-ink-500">
                            {new Date(alert.created_at).toLocaleTimeString()}
                          </span>
                          {alert.vehicle_id && (
                            <button
                              onClick={() => setSelectedId(alert.vehicle_id)}
                              className="text-[10px] text-electric-300 hover:text-electric-200"
                            >
                              Show on map
                            </button>
                          )}
                          {alert.status !== "acknowledged" && (
                            <button
                              onClick={() => acknowledgeAlert(alert.id)}
                              className="text-[10px] text-ink-400 hover:text-ink-200"
                            >
                              {strings.live.acknowledge}
                            </button>
                          )}
                          <button
                            onClick={() => resolveAlert(alert.id)}
                            className="text-[10px] text-ink-400 hover:text-ink-200"
                          >
                            {strings.live.resolve}
                          </button>
                        </div>
                      </div>
                    </div>
                  </li>
                ))
              )}
            </ul>
          )}
        </aside>
      </div>

      {/* --- KPI strip --- */}
      <div className="grid shrink-0 grid-cols-2 gap-px border-t border-ink-700 bg-ink-700 lg:grid-cols-5">
        <Kpi
          label={strings.live.kpiActive}
          value={kpis ? `${kpis.active_now}/${kpis.total_vehicles}` : "—"}
        />
        <Kpi label="Stopped" value={kpis?.idle ?? "—"} />
        <Kpi
          label={strings.live.kpiAlerts}
          value={kpis?.active_alerts ?? "—"}
          tone={kpis && kpis.active_alerts > 0 ? "alert" : undefined}
        />
        <Kpi
          label={strings.live.kpiNotTracked}
          value={kpis?.not_tracked ?? "—"}
          hint={
            kpis && kpis.not_tracked > 0 ? strings.live.notTrackedNudge : undefined
          }
        />
        <Kpi
          label={strings.live.kpiDistance}
          value={kpis ? `${kpis.distance_today_km.toFixed(1)} km` : "—"}
        />
      </div>

      {error && (
        <p
          role="alert"
          className="shrink-0 bg-danger/10 px-4 py-2 text-xs text-danger"
        >
          {error}
        </p>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-ink-400">{label}</dt>
      <dd className="truncate text-ink-100">{value}</dd>
    </div>
  );
}

function Kpi({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "alert";
}) {
  return (
    <div className="bg-ink-800 px-4 py-2.5">
      <p className="text-[10px] font-medium uppercase tracking-wider text-ink-400">
        {label}
      </p>
      <p
        className={`fb-numeric mt-0.5 text-lg font-semibold ${
          tone === "alert" ? "text-coral" : "text-white"
        }`}
      >
        {value}
      </p>
      {hint && <p className="text-[10px] text-ink-500">{hint}</p>}
    </div>
  );
}

function timeOnly(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
