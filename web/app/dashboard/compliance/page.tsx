"use client";

/** Insurance, registration and inspection records with expiry (Section 4.9). */

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError, api } from "@/lib/api";
import { strings } from "@/lib/strings";
import type { ComplianceDocument, Driver, Page, Vehicle } from "@/lib/types";
import { DataTable, type Column } from "@/components/DataTable";

const DOCUMENT_TYPES = [
  "insurance",
  "registration",
  "inspection",
  "license",
  "other",
] as const;

export default function CompliancePage() {
  const [documents, setDocuments] = useState<ComplianceDocument[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    document_type: "insurance",
    title: "",
    attach_to: "vehicle",
    vehicle_id: "",
    driver_id: "",
    expires_on: "",
    cost: "",
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [documentPage, vehiclePage, driverPage] = await Promise.all([
        api.get<Page<ComplianceDocument>>("/compliance/documents"),
        api.get<Page<Vehicle>>("/vehicles?limit=200"),
        api.get<Page<Driver>>("/drivers?limit=200"),
      ]);
      setDocuments(documentPage.items);
      setVehicles(vehiclePage.items);
      setDrivers(driverPage.items);
      setForm((f) => ({
        ...f,
        vehicle_id: f.vehicle_id || vehiclePage.items[0]?.id || "",
        driver_id: f.driver_id || driverPage.items[0]?.id || "",
      }));
      setError(null);
    } catch {
      setError("We could not load your documents.");
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
      await api.post("/compliance/documents", {
        document_type: form.document_type,
        title: form.title,
        vehicle_id: form.attach_to === "vehicle" ? form.vehicle_id : null,
        driver_id: form.attach_to === "driver" ? form.driver_id : null,
        expires_on: form.expires_on || null,
        cost: form.cost ? Number(form.cost) : null,
      });
      setShowForm(false);
      setForm({ ...form, title: "", expires_on: "", cost: "" });
      await load();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "We could not save that document.",
      );
    } finally {
      setSaving(false);
    }
  }

  function subjectName(document: ComplianceDocument): string {
    if (document.vehicle_id) {
      return vehicles.find((v) => v.id === document.vehicle_id)?.name ?? "Vehicle";
    }
    if (document.driver_id) {
      return drivers.find((d) => d.id === document.driver_id)?.full_name ?? "Driver";
    }
    return "—";
  }

  const columns: Column<ComplianceDocument>[] = [
    { key: "title", header: "Document", render: (r) => r.title },
    { key: "type", header: "Type", render: (r) => r.document_type },
    { key: "subject", header: "Attached to", render: subjectName },
    { key: "expires", header: "Expires", render: (r) => r.expires_on ?? "—" },
    {
      key: "status",
      header: "Status",
      render: (r) => {
        if (r.days_until_expiry == null) {
          return <span className="text-xs text-ink-400">No expiry</span>;
        }
        if (r.days_until_expiry < 0) {
          return (
            <span className="fb-badge bg-danger/10 text-danger">
              Expired {Math.abs(r.days_until_expiry)}d ago
            </span>
          );
        }
        if (r.days_until_expiry <= 30) {
          return (
            <span className="fb-badge bg-warning/10 text-warning">
              {r.days_until_expiry}d left
            </span>
          );
        }
        return (
          <span className="fb-badge bg-success/10 text-success">
            {r.days_until_expiry}d left
          </span>
        );
      },
    },
  ];

  const expiringSoon = documents.filter(
    (d) => d.days_until_expiry != null && d.days_until_expiry <= 30,
  ).length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white">{strings.nav.compliance}</h1>
          <p className="mt-1 text-sm text-ink-300">
            Anything expiring within 30 days raises an alert automatically.
          </p>
        </div>
        <button onClick={() => setShowForm((o) => !o)} className="fb-button-primary">
          {showForm ? strings.common.cancel : "Add document"}
        </button>
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      {expiringSoon > 0 && (
        <p className="rounded-lg border border-warning/40 bg-warning/10 px-4 py-2.5 text-sm text-warning">
          {expiringSoon} document{expiringSoon === 1 ? "" : "s"} expiring within 30 days.
        </p>
      )}

      {showForm && (
        <form onSubmit={submit} className="fb-card space-y-4 p-5">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <label className="space-y-1.5">
              <span className="fb-label">Type</span>
              <select
                value={form.document_type}
                onChange={(e) => setForm({ ...form, document_type: e.target.value })}
                className="fb-input"
              >
                {DOCUMENT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1.5">
              <span className="fb-label">Title</span>
              <input
                required
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                className="fb-input"
                placeholder="Fleet insurance 2026"
              />
            </label>
            <label className="space-y-1.5">
              <span className="fb-label">Attach to</span>
              <select
                value={form.attach_to}
                onChange={(e) => setForm({ ...form, attach_to: e.target.value })}
                className="fb-input"
              >
                <option value="vehicle">Vehicle</option>
                <option value="driver">Driver</option>
              </select>
            </label>
            {form.attach_to === "vehicle" ? (
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
            ) : (
              <label className="space-y-1.5">
                <span className="fb-label">Driver</span>
                <select
                  value={form.driver_id}
                  onChange={(e) => setForm({ ...form, driver_id: e.target.value })}
                  className="fb-input"
                >
                  {drivers.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.full_name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="space-y-1.5">
              <span className="fb-label">Expires on</span>
              <input
                type="date"
                value={form.expires_on}
                onChange={(e) => setForm({ ...form, expires_on: e.target.value })}
                className="fb-input"
              />
            </label>
            <label className="space-y-1.5">
              <span className="fb-label">Cost</span>
              <input
                type="number"
                step="0.01"
                min={0}
                value={form.cost}
                onChange={(e) => setForm({ ...form, cost: e.target.value })}
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
        <DataTable
          columns={columns}
          rows={documents}
          loading={loading}
          empty="No documents recorded yet."
        />
      </section>
    </div>
  );
}
