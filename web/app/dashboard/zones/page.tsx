"use client";

/**
 * Geofence and POI management lists (Section 4d).
 *
 * Drawing happens on the live map - this is the separate list view for
 * reviewing, renaming, toggling and deleting what has been drawn.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import type { Geofence, Poi } from "@/lib/types";
import { DataTable, type Column } from "@/components/DataTable";

const TRIGGERS = ["on_enter", "on_exit", "both"] as const;

export default function ZonesPage() {
  const { session } = useSession();
  const isAdmin = session?.user.role === "org_admin";

  const [geofences, setGeofences] = useState<Geofence[]>([]);
  const [pois, setPois] = useState<Poi[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [fences, points] = await Promise.all([
        api.get<Geofence[]>("/geofences"),
        api.get<Poi[]>("/pois"),
      ]);
      setGeofences(fences);
      setPois(points);
      setError(null);
    } catch {
      setError("We could not load your zones.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function patchGeofence(id: string, body: Record<string, unknown>) {
    try {
      const updated = await api.patch<Geofence>(`/geofences/${id}`, body);
      setGeofences((current) => current.map((f) => (f.id === id ? updated : f)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That change did not save.");
    }
  }

  async function removeGeofence(fence: Geofence) {
    if (!window.confirm(`Delete the geofence "${fence.name}"?`)) return;
    try {
      await api.delete(`/geofences/${fence.id}`);
      setGeofences((current) => current.filter((f) => f.id !== fence.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We could not delete that.");
    }
  }

  async function removePoi(poi: Poi) {
    if (!window.confirm(`Delete the POI "${poi.name}"?`)) return;
    try {
      await api.delete(`/pois/${poi.id}`);
      setPois((current) => current.filter((p) => p.id !== poi.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We could not delete that.");
    }
  }

  const geofenceColumns: Column<Geofence>[] = [
    {
      key: "name",
      header: "Geofence",
      render: (r) => (
        <span className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="h-2.5 w-2.5 rounded-sm"
            style={{ backgroundColor: r.color }}
          />
          {r.name}
        </span>
      ),
    },
    { key: "shape", header: "Shape", render: (r) => r.shape },
    {
      key: "scope",
      header: "Applies to",
      render: (r) =>
        r.vehicle_ids.length === 0
          ? "All vehicles"
          : `${r.vehicle_ids.length} vehicle${r.vehicle_ids.length === 1 ? "" : "s"}`,
    },
    {
      key: "trigger",
      header: "Trigger",
      render: (r) =>
        isAdmin ? (
          <select
            value={r.trigger}
            onChange={(e) => patchGeofence(r.id, { trigger: e.target.value })}
            className="fb-input !py-1 !text-xs"
          >
            {TRIGGERS.map((t) => (
              <option key={t} value={t}>
                {t.replace("_", " ")}
              </option>
            ))}
          </select>
        ) : (
          r.trigger.replace("_", " ")
        ),
    },
    {
      key: "active",
      header: "Active",
      render: (r) =>
        isAdmin ? (
          <button
            onClick={() => patchGeofence(r.id, { is_active: !r.is_active })}
            className={`fb-badge ${
              r.is_active ? "bg-success/10 text-success" : "bg-ink-600 text-ink-300"
            }`}
          >
            {r.is_active ? "Active" : "Paused"}
          </button>
        ) : (
          <span className="fb-badge bg-ink-600 text-ink-300">
            {r.is_active ? "Active" : "Paused"}
          </span>
        ),
    },
    {
      key: "delete",
      header: "",
      render: (r) =>
        isAdmin ? (
          <button
            onClick={() => removeGeofence(r)}
            className="text-xs text-danger hover:underline"
          >
            Delete
          </button>
        ) : null,
    },
  ];

  const poiColumns: Column<Poi>[] = [
    { key: "name", header: "Point of interest", render: (r) => r.name },
    { key: "category", header: "Category", render: (r) => r.category.replace("_", " ") },
    {
      key: "position",
      header: "Position",
      render: (r) => `${r.latitude.toFixed(4)}, ${r.longitude.toFixed(4)}`,
    },
    {
      key: "delete",
      header: "",
      render: (r) => (
        <button
          onClick={() => removePoi(r)}
          className="text-xs text-danger hover:underline"
        >
          Delete
        </button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-white">Zones & places</h1>
        <p className="mt-1 text-sm text-ink-300">
          Geofences and points of interest are drawn on the{" "}
          <Link href="/dashboard" className="text-electric-300 hover:text-electric-200">
            live map
          </Link>
          . Manage them here.
        </p>
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      <section className="fb-card">
        <h2 className="border-b border-ink-600/70 px-4 py-2.5 text-sm font-semibold text-white">
          Geofences
        </h2>
        <DataTable
          columns={geofenceColumns}
          rows={geofences}
          loading={loading}
          empty="No geofences yet. Draw one on the live map."
        />
      </section>

      <section className="fb-card">
        <h2 className="border-b border-ink-600/70 px-4 py-2.5 text-sm font-semibold text-white">
          Points of interest
        </h2>
        <DataTable
          columns={poiColumns}
          rows={pois}
          loading={loading}
          empty="No points of interest yet."
        />
      </section>
    </div>
  );
}
