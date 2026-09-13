"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import type { Page, Vehicle } from "@/lib/types";
import { StatusDot, statusLabel } from "@/components/StatusDot";

const EMPTY_FORM = {
  name: "",
  license_plate: "",
  make: "",
  model: "",
  year: "",
  vehicle_type: "van",
  fuel_type: "diesel",
  odometer_km: "",
};

export default function VehiclesPage() {
  const { session } = useSession();
  const canEdit = session?.user.role === "org_admin";

  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(async (term: string) => {
    setLoading(true);
    try {
      const query = term.trim()
        ? `?limit=200&search=${encodeURIComponent(term.trim())}`
        : "?limit=200";
      setVehicles((await api.get<Page<Vehicle>>(`/vehicles${query}`)).items);
      setError(null);
    } catch {
      setError("We could not load the vehicle registry.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void load(search), 250);
    return () => clearTimeout(timer);
  }, [search, load]);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      await api.post<Vehicle>("/vehicles", {
        name: form.name,
        license_plate: form.license_plate,
        make: form.make || null,
        model: form.model || null,
        year: form.year ? Number(form.year) : null,
        vehicle_type: form.vehicle_type,
        fuel_type: form.fuel_type,
        odometer_km: form.odometer_km ? Number(form.odometer_km) : 0,
      });
      setForm(EMPTY_FORM);
      setShowForm(false);
      await load(search);
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "We could not save that vehicle.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white">
            {strings.dashboard.vehiclesTitle}
          </h1>
          <p className="mt-1 text-sm text-ink-300">
            Your fleet registry. GPS devices are fitted and linked by FleetBeat.
          </p>
        </div>
        {canEdit && (
          <button
            onClick={() => setShowForm((open) => !open)}
            className="fb-button-primary"
          >
            {showForm ? strings.common.cancel : "Add vehicle"}
          </button>
        )}
      </div>

      {showForm && canEdit && (
        <form onSubmit={handleCreate} className="fb-card space-y-4 p-5">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Name" required>
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="fb-input"
                placeholder="Van 01"
              />
            </Field>
            <Field label="License plate" required>
              <input
                required
                value={form.license_plate}
                onChange={(e) =>
                  setForm({ ...form, license_plate: e.target.value })
                }
                className="fb-input"
                placeholder="AB-123-CD"
              />
            </Field>
            <Field label="Make">
              <input
                value={form.make}
                onChange={(e) => setForm({ ...form, make: e.target.value })}
                className="fb-input"
              />
            </Field>
            <Field label="Model">
              <input
                value={form.model}
                onChange={(e) => setForm({ ...form, model: e.target.value })}
                className="fb-input"
              />
            </Field>
            <Field label="Year">
              <input
                type="number"
                min={1900}
                max={2100}
                value={form.year}
                onChange={(e) => setForm({ ...form, year: e.target.value })}
                className="fb-input"
              />
            </Field>
            <Field label="Odometer (km)">
              <input
                type="number"
                min={0}
                value={form.odometer_km}
                onChange={(e) =>
                  setForm({ ...form, odometer_km: e.target.value })
                }
                className="fb-input"
              />
            </Field>
            <Field label="Type">
              <select
                value={form.vehicle_type}
                onChange={(e) =>
                  setForm({ ...form, vehicle_type: e.target.value })
                }
                className="fb-input"
              >
                {["car", "van", "truck", "ev", "other"].map((value) => (
                  <option key={value} value={value}>
                    {value.toUpperCase()}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Fuel">
              <select
                value={form.fuel_type}
                onChange={(e) => setForm({ ...form, fuel_type: e.target.value })}
                className="fb-input"
              >
                {["petrol", "diesel", "electric", "hybrid", "lpg"].map(
                  (value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ),
                )}
              </select>
            </Field>
          </div>

          {formError && (
            <p role="alert" className="text-sm text-danger">
              {formError}
            </p>
          )}

          <button
            type="submit"
            disabled={saving}
            className="fb-button-primary"
          >
            {saving ? "Saving…" : strings.common.save}
          </button>
        </form>
      )}

      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="fb-input max-w-sm"
        placeholder="Search by name, plate or VIN"
        aria-label={strings.common.search}
      />

      <section className="fb-card overflow-x-auto">
        {error ? (
          <p className="px-4 py-6 text-sm text-danger">{error}</p>
        ) : loading ? (
          <p className="px-4 py-6 text-sm text-ink-400">
            {strings.common.loading}
          </p>
        ) : vehicles.length === 0 ? (
          <p className="px-4 py-6 text-sm text-ink-400">
            {strings.common.empty}
          </p>
        ) : (
          <table className="w-full min-w-[46rem] text-left text-sm">
            <thead className="border-b border-ink-600/70 text-xs uppercase tracking-wide text-ink-400">
              <tr>
                <th className="px-4 py-2.5 font-medium">Vehicle</th>
                <th className="px-4 py-2.5 font-medium">Plate</th>
                <th className="px-4 py-2.5 font-medium">Type</th>
                <th className="px-4 py-2.5 font-medium">Odometer</th>
                <th className="px-4 py-2.5 font-medium">GPS device</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-600/50">
              {vehicles.map((vehicle) => (
                <tr key={vehicle.id} className="hover:bg-ink-700/40">
                  <td className="px-4 py-3">
                    <span className="font-medium text-ink-50">
                      {vehicle.name}
                    </span>
                    {(vehicle.make || vehicle.model) && (
                      <span className="block text-xs text-ink-400">
                        {[vehicle.make, vehicle.model, vehicle.year]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-ink-200">
                    {vehicle.license_plate}
                  </td>
                  <td className="px-4 py-3 text-ink-300">
                    {vehicle.vehicle_type}
                  </td>
                  <td className="fb-numeric px-4 py-3 text-ink-300">
                    {Math.round(vehicle.odometer_km).toLocaleString()} km
                  </td>
                  <td className="px-4 py-3">
                    {vehicle.device ? (
                      /* Read-only: customers never manage devices (Section 9). */
                      <span className="font-mono text-xs text-ink-200">
                        {vehicle.device.serial_number}
                        <span className="ml-2 text-ink-500">
                          {vehicle.device.status}
                        </span>
                      </span>
                    ) : (
                      <span
                        className="text-xs text-ink-500"
                        title={strings.dashboard.notTrackedHint}
                      >
                        {strings.dashboard.notTracked}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center gap-2">
                      <StatusDot status={vehicle.live_status} />
                      <span className="text-xs text-ink-300">
                        {statusLabel(vehicle.live_status)}
                      </span>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="space-y-1.5">
      <span className="fb-label">
        {label}
        {required && <span className="ml-1 text-coral">*</span>}
      </span>
      {children}
    </label>
  );
}
