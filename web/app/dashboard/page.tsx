"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { api } from "@/lib/api";
import { strings } from "@/lib/strings";
import type { Driver, Page, Vehicle } from "@/lib/types";
import { StatusDot, statusLabel } from "@/components/StatusDot";

/**
 * Live Tracking home - the first screen every dashboard user sees
 * (Section 4b).
 *
 * Phase 1 ships the page frame and the real vehicle roster with live-status
 * classification already wired to the API. The map, WebSocket feed, KPI
 * strip and alerts feed land in Phase 2, once devices exist and the GPS
 * simulation engine is producing positions.
 */
export default function LiveTrackingPage() {
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [driverCount, setDriverCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [vehiclePage, driverPage] = await Promise.all([
          api.get<Page<Vehicle>>("/vehicles?limit=200"),
          api.get<Page<Driver>>("/drivers?limit=1"),
        ]);
        if (cancelled) return;
        setVehicles(vehiclePage.items);
        setDriverCount(driverPage.total);
      } catch {
        if (!cancelled) setError("We could not load your fleet just now.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const tracked = vehicles.filter((v) => v.is_tracked).length;
  const notTracked = vehicles.length - tracked;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-white">
          {strings.dashboard.liveTitle}
        </h1>
        <p className="mt-1 text-sm text-ink-300">
          {strings.dashboard.liveSubtitle}
        </p>
      </div>

      {/* Bottom KPI strip of Section 4b, shown here until the map arrives. */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Vehicles" value={vehicles.length} loading={loading} />
        <Kpi label="Live tracked" value={tracked} loading={loading} />
        <Kpi
          label="Not tracked"
          value={notTracked}
          loading={loading}
          hint={notTracked > 0 ? "Awaiting a GPS device" : undefined}
        />
        <Kpi label="Drivers" value={driverCount} loading={loading} />
      </div>

      <section className="fb-card overflow-hidden">
        <div className="flex items-center justify-between border-b border-ink-600/70 px-4 py-3">
          <h2 className="text-sm font-semibold text-white">
            {strings.dashboard.vehiclesTitle}
          </h2>
          <Link
            href="/dashboard/vehicles"
            className="text-xs font-medium text-electric-300 hover:text-electric-200"
          >
            Manage
          </Link>
        </div>

        {error ? (
          <p className="px-4 py-6 text-sm text-danger">{error}</p>
        ) : loading ? (
          <p className="px-4 py-6 text-sm text-ink-400">
            {strings.common.loading}
          </p>
        ) : vehicles.length === 0 ? (
          <p className="px-4 py-6 text-sm text-ink-400">
            No vehicles yet. Add your first one from the Vehicles page.
          </p>
        ) : (
          <ul className="divide-y divide-ink-600/50">
            {vehicles.map((vehicle) => (
              <li
                key={vehicle.id}
                className="flex items-center justify-between gap-4 px-4 py-3"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <StatusDot status={vehicle.live_status} />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink-50">
                      {vehicle.name}
                    </p>
                    <p className="truncate text-xs text-ink-400">
                      {vehicle.license_plate}
                    </p>
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-xs text-ink-300">
                    {statusLabel(vehicle.live_status)}
                  </p>
                  {!vehicle.is_tracked && (
                    <p className="text-[11px] text-ink-500">
                      {strings.dashboard.notTracked}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="rounded-lg border border-dashed border-ink-600 px-4 py-3 text-xs leading-relaxed text-ink-400">
        {strings.dashboard.comingInPhase2}
      </p>
    </div>
  );
}

function Kpi({
  label,
  value,
  loading,
  hint,
}: {
  label: string;
  value: number;
  loading: boolean;
  hint?: string;
}) {
  return (
    <div className="fb-card px-4 py-3">
      <p className="fb-label">{label}</p>
      <p className="fb-numeric mt-1 text-2xl font-semibold text-white">
        {loading ? "—" : value}
      </p>
      {hint && <p className="mt-0.5 text-[11px] text-ink-400">{hint}</p>}
    </div>
  );
}
