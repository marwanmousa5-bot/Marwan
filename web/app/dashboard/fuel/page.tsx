"use client";

/** Fuel and energy logging, with the CO2 rollup (Sections 4.7 and 4.17). */

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError, api } from "@/lib/api";
import { strings } from "@/lib/strings";
import type { FuelLog, FuelSummaryRow, Page, Vehicle } from "@/lib/types";
import { DataTable, type Column } from "@/components/DataTable";

const FUEL_TYPES = ["diesel", "petrol", "electric", "hybrid", "lpg"] as const;

export default function FuelPage() {
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [logs, setLogs] = useState<FuelLog[]>([]);
  const [summary, setSummary] = useState<FuelSummaryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    vehicle_id: "",
    fuel_type: "diesel",
    quantity: "",
    total_cost: "",
    odometer_km: "",
    location_name: "",
  });

  const vehicleName = useCallback(
    (id: string) => vehicles.find((v) => v.id === id)?.name ?? "—",
    [vehicles],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [vehiclePage, logPage, summaryRows] = await Promise.all([
        api.get<Page<Vehicle>>("/vehicles?limit=200"),
        api.get<Page<FuelLog>>("/fuel/logs?limit=100"),
        api.get<FuelSummaryRow[]>("/fuel/summary"),
      ]);
      setVehicles(vehiclePage.items);
      setLogs(logPage.items);
      setSummary(summaryRows);
      setForm((f) => ({
        ...f,
        vehicle_id: f.vehicle_id || vehiclePage.items[0]?.id || "",
      }));
      setError(null);
    } catch {
      setError("We could not load your fuel data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await api.post("/fuel/logs", {
        vehicle_id: form.vehicle_id,
        fuel_type: form.fuel_type,
        quantity: Number(form.quantity),
        unit: form.fuel_type === "electric" ? "kWh" : "L",
        total_cost: Number(form.total_cost),
        odometer_km: form.odometer_km ? Number(form.odometer_km) : null,
        location_name: form.location_name || null,
        filled_at: new Date().toISOString(),
      });
      setShowForm(false);
      setForm({ ...form, quantity: "", total_cost: "", odometer_km: "" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We could not save that entry.");
    } finally {
      setSaving(false);
    }
  }

  const totalCo2 = summary.reduce((sum, row) => sum + row.total_co2_kg, 0);
  const totalCost = summary.reduce((sum, row) => sum + row.total_cost, 0);

  const summaryColumns: Column<FuelSummaryRow & { id: string }>[] = [
    { key: "vehicle", header: "Vehicle", render: (r) => r.vehicle_name },
    { key: "entries", header: "Entries", numeric: true, render: (r) => r.entries },
    {
      key: "quantity",
      header: "Quantity",
      numeric: true,
      render: (r) => r.total_quantity.toFixed(1),
    },
    {
      key: "consumption",
      header: "L/100km",
      numeric: true,
      render: (r) => (r.litres_per_100km != null ? r.litres_per_100km.toFixed(1) : "—"),
    },
    {
      key: "cost",
      header: "Cost",
      numeric: true,
      render: (r) => r.total_cost.toFixed(2),
    },
    {
      key: "co2",
      header: "CO₂ (kg)",
      numeric: true,
      render: (r) => r.total_co2_kg.toFixed(1),
    },
  ];

  const logColumns: Column<FuelLog>[] = [
    {
      key: "date",
      header: "When",
      render: (r) => new Date(r.filled_at).toLocaleDateString(),
    },
    { key: "vehicle", header: "Vehicle", render: (r) => vehicleName(r.vehicle_id) },
    { key: "type", header: "Type", render: (r) => r.fuel_type },
    {
      key: "quantity",
      header: "Quantity",
      numeric: true,
      render: (r) => `${r.quantity} ${r.unit}`,
    },
    {
      key: "cost",
      header: "Cost",
      numeric: true,
      render: (r) => r.total_cost.toFixed(2),
    },
    {
      key: "co2",
      header: "CO₂ (kg)",
      numeric: true,
      render: (r) => (r.co2_kg != null ? r.co2_kg.toFixed(1) : "—"),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white">{strings.nav.fuel}</h1>
          <p className="mt-1 text-sm text-ink-300">
            Manual entry for now. CO₂ is derived from your organization&apos;s
            emission factors.
          </p>
        </div>
        <button onClick={() => setShowForm((o) => !o)} className="fb-button-primary">
          {showForm ? strings.common.cancel : "Log fill-up"}
        </button>
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Entries" value={logs.length} />
        <Stat label="Vehicles logged" value={summary.length} />
        <Stat label="Total cost" value={totalCost.toFixed(2)} />
        <Stat label="Total CO₂" value={`${totalCo2.toFixed(0)} kg`} />
      </div>

      {showForm && (
        <form onSubmit={submit} className="fb-card space-y-4 p-5">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <label className="space-y-1.5">
              <span className="fb-label">Vehicle</span>
              <select
                value={form.vehicle_id}
                onChange={(e) => setForm({ ...form, vehicle_id: e.target.value })}
                className="fb-input"
              >
                {vehicles.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1.5">
              <span className="fb-label">Fuel type</span>
              <select
                value={form.fuel_type}
                onChange={(e) => setForm({ ...form, fuel_type: e.target.value })}
                className="fb-input"
              >
                {FUEL_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1.5">
              <span className="fb-label">
                Quantity ({form.fuel_type === "electric" ? "kWh" : "L"})
              </span>
              <input
                required
                type="number"
                step="0.01"
                min={0.01}
                value={form.quantity}
                onChange={(e) => setForm({ ...form, quantity: e.target.value })}
                className="fb-input"
              />
            </label>
            <label className="space-y-1.5">
              <span className="fb-label">Total cost</span>
              <input
                required
                type="number"
                step="0.01"
                min={0}
                value={form.total_cost}
                onChange={(e) => setForm({ ...form, total_cost: e.target.value })}
                className="fb-input"
              />
            </label>
            <label className="space-y-1.5">
              <span className="fb-label">Odometer (km)</span>
              <input
                type="number"
                min={0}
                value={form.odometer_km}
                onChange={(e) => setForm({ ...form, odometer_km: e.target.value })}
                className="fb-input"
              />
            </label>
            <label className="space-y-1.5">
              <span className="fb-label">Location</span>
              <input
                value={form.location_name}
                onChange={(e) => setForm({ ...form, location_name: e.target.value })}
                className="fb-input"
              />
            </label>
          </div>
          <button type="submit" disabled={saving} className="fb-button-primary">
            {saving ? "Saving…" : strings.common.save}
          </button>
        </form>
      )}

      <section className="fb-card">
        <h2 className="border-b border-ink-600/70 px-4 py-2.5 text-sm font-semibold text-white">
          Per vehicle
        </h2>
        <DataTable
          columns={summaryColumns}
          rows={summary.map((row) => ({ ...row, id: row.vehicle_id }))}
          loading={loading}
          empty="No fuel entries yet."
        />
      </section>

      <section className="fb-card">
        <h2 className="border-b border-ink-600/70 px-4 py-2.5 text-sm font-semibold text-white">
          Recent entries
        </h2>
        <DataTable columns={logColumns} rows={logs} loading={loading} />
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="fb-card px-4 py-3">
      <p className="fb-label">{label}</p>
      <p className="fb-numeric mt-1 text-xl font-semibold text-white">{value}</p>
    </div>
  );
}
