"use client";

/** Preventive maintenance schedules and work orders (Section 4 item 6). */

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import type { MaintenanceSchedule, Page, Vehicle, WorkOrder } from "@/lib/types";
import { DataTable, type Column } from "@/components/DataTable";

export default function MaintenancePage() {
  const { session } = useSession();
  const isAdmin = session?.user.role === "org_admin";

  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [schedules, setSchedules] = useState<MaintenanceSchedule[]>([]);
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showScheduleForm, setShowScheduleForm] = useState(false);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState({
    vehicle_id: "",
    name: "",
    interval_type: "mileage",
    interval_km: "10000",
    interval_days: "365",
    last_service_odometer_km: "",
  });

  const vehicleName = useCallback(
    (id: string) => vehicles.find((v) => v.id === id)?.name ?? "—",
    [vehicles],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [vehiclePage, scheduleRows, orderPage] = await Promise.all([
        api.get<Page<Vehicle>>("/vehicles?limit=200"),
        api.get<MaintenanceSchedule[]>("/maintenance/schedules"),
        api.get<Page<WorkOrder>>("/maintenance/work-orders?limit=100"),
      ]);
      setVehicles(vehiclePage.items);
      setSchedules(scheduleRows);
      setWorkOrders(orderPage.items);
      setForm((f) => ({
        ...f,
        vehicle_id: f.vehicle_id || vehiclePage.items[0]?.id || "",
      }));
      setError(null);
    } catch {
      setError("We could not load your maintenance data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function createSchedule(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await api.post("/maintenance/schedules", {
        vehicle_id: form.vehicle_id,
        name: form.name,
        interval_type: form.interval_type,
        interval_km:
          form.interval_type === "mileage" ? Number(form.interval_km) : null,
        interval_days:
          form.interval_type === "time" ? Number(form.interval_days) : null,
        last_service_odometer_km: form.last_service_odometer_km
          ? Number(form.last_service_odometer_km)
          : null,
      });
      setShowScheduleForm(false);
      setForm({ ...form, name: "" });
      await load();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "We could not save that schedule.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function raiseWorkOrder(schedule: MaintenanceSchedule) {
    try {
      await api.post("/maintenance/work-orders", {
        vehicle_id: schedule.vehicle_id,
        schedule_id: schedule.id,
        title: schedule.name,
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We could not open that job.");
    }
  }

  async function completeWorkOrder(order: WorkOrder) {
    try {
      await api.patch(`/maintenance/work-orders/${order.id}`, { status: "completed" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We could not complete that job.");
    }
  }

  const scheduleColumns: Column<MaintenanceSchedule>[] = [
    { key: "name", header: "Schedule", render: (r) => r.name },
    { key: "vehicle", header: "Vehicle", render: (r) => vehicleName(r.vehicle_id) },
    {
      key: "interval",
      header: "Interval",
      render: (r) =>
        r.interval_type === "mileage"
          ? `${(r.interval_km ?? 0).toLocaleString()} km`
          : `${r.interval_days} days`,
    },
    {
      key: "due",
      header: "Next due",
      render: (r) =>
        r.next_due_odometer_km
          ? `${Math.round(r.next_due_odometer_km).toLocaleString()} km`
          : (r.next_due_date ?? "—"),
    },
    {
      key: "action",
      header: "",
      render: (r) => (
        <button
          onClick={() => raiseWorkOrder(r)}
          className="text-xs text-electric-300 hover:text-electric-200"
        >
          Open job
        </button>
      ),
    },
  ];

  const orderColumns: Column<WorkOrder>[] = [
    { key: "title", header: "Work order", render: (r) => r.title },
    { key: "vehicle", header: "Vehicle", render: (r) => vehicleName(r.vehicle_id) },
    {
      key: "status",
      header: "Status",
      render: (r) => (
        <span
          className={`fb-badge ${
            r.status === "completed"
              ? "bg-success/10 text-success"
              : r.status === "cancelled"
                ? "bg-ink-600 text-ink-300"
                : "bg-warning/10 text-warning"
          }`}
        >
          {r.status.replace("_", " ")}
        </span>
      ),
    },
    {
      key: "cost",
      header: "Cost",
      numeric: true,
      render: (r) => (r.total_cost != null ? r.total_cost.toFixed(2) : "—"),
    },
    {
      key: "action",
      header: "",
      render: (r) =>
        r.status === "completed" || r.status === "cancelled" ? null : (
          <button
            onClick={() => completeWorkOrder(r)}
            className="text-xs text-electric-300 hover:text-electric-200"
          >
            Mark complete
          </button>
        ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white">{strings.nav.maintenance}</h1>
          <p className="mt-1 text-sm text-ink-300">
            Schedules drive the alerts; completing a job writes service history and
            advances the next due date.
          </p>
        </div>
        {isAdmin && (
          <button
            onClick={() => setShowScheduleForm((open) => !open)}
            className="fb-button-primary"
          >
            {showScheduleForm ? strings.common.cancel : "Add schedule"}
          </button>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      {showScheduleForm && isAdmin && (
        <form onSubmit={createSchedule} className="fb-card space-y-4 p-5">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
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
              <span className="fb-label">Name</span>
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="fb-input"
                placeholder="Oil change"
              />
            </label>
            <label className="space-y-1.5">
              <span className="fb-label">Interval type</span>
              <select
                value={form.interval_type}
                onChange={(e) => setForm({ ...form, interval_type: e.target.value })}
                className="fb-input"
              >
                <option value="mileage">Mileage</option>
                <option value="time">Time</option>
              </select>
            </label>
            {form.interval_type === "mileage" ? (
              <label className="space-y-1.5">
                <span className="fb-label">Every (km)</span>
                <input
                  type="number"
                  min={1}
                  value={form.interval_km}
                  onChange={(e) => setForm({ ...form, interval_km: e.target.value })}
                  className="fb-input"
                />
              </label>
            ) : (
              <label className="space-y-1.5">
                <span className="fb-label">Every (days)</span>
                <input
                  type="number"
                  min={1}
                  value={form.interval_days}
                  onChange={(e) => setForm({ ...form, interval_days: e.target.value })}
                  className="fb-input"
                />
              </label>
            )}
          </div>
          <button type="submit" disabled={saving} className="fb-button-primary">
            {saving ? "Saving…" : strings.common.save}
          </button>
        </form>
      )}

      <section className="fb-card">
        <h2 className="border-b border-ink-600/70 px-4 py-2.5 text-sm font-semibold text-white">
          Schedules
        </h2>
        <DataTable
          columns={scheduleColumns}
          rows={schedules}
          loading={loading}
          empty="No maintenance schedules yet."
        />
      </section>

      <section className="fb-card">
        <h2 className="border-b border-ink-600/70 px-4 py-2.5 text-sm font-semibold text-white">
          Work orders
        </h2>
        <DataTable
          columns={orderColumns}
          rows={workOrders}
          loading={loading}
          empty="No work orders yet."
        />
      </section>
    </div>
  );
}
