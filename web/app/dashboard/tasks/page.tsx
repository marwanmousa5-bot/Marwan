"use client";

/**
 * Task Manager board (Section 4f).
 *
 * A Kanban board over the mandatory four-state lifecycle. Creating a task
 * picks the destination on a map and previews the real route and ETA before
 * anything is assigned; cancelled tasks get their own column so they stay
 * visible without cluttering the working columns.
 */

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import dynamic from "next/dynamic";

import { ApiError, api } from "@/lib/api";
import { strings } from "@/lib/strings";
import type {
  Driver,
  Page,
  Poi,
  RoutePreview,
  Task,
  TaskStatus,
} from "@/lib/types";

const DestinationPicker = dynamic(
  () => import("@/components/map/DestinationPicker").then((m) => m.DestinationPicker),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center bg-ink-800 text-xs text-ink-400">
        {strings.common.loading}
      </div>
    ),
  },
);

const COLUMNS: { status: TaskStatus; label: string }[] = [
  { status: "assigned", label: strings.tasks.columns.assigned },
  { status: "accepted", label: strings.tasks.columns.accepted },
  { status: "en_route", label: strings.tasks.columns.en_route },
  { status: "completed", label: strings.tasks.columns.completed },
];

const TASK_TYPES = ["delivery", "pickup", "service_call", "custom"] as const;

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [pois, setPois] = useState<Poi[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [selected, setSelected] = useState<Task | null>(null);

  const [form, setForm] = useState({
    title: "",
    description: "",
    task_type: "delivery",
    priority: "normal",
    driver_id: "",
    destination_label: "",
    due_at: "",
  });
  const [destination, setDestination] = useState<{ lat: number; lng: number } | null>(
    null,
  );
  const [preview, setPreview] = useState<RoutePreview | null>(null);
  const [previewNote, setPreviewNote] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [taskPage, driverPage, poiRows] = await Promise.all([
        api.get<Page<Task>>("/tasks?limit=200"),
        api.get<Page<Driver>>("/drivers?limit=200"),
        api.get<Poi[]>("/pois"),
      ]);
      setTasks(taskPage.items);
      setDrivers(driverPage.items);
      setPois(poiRows);
      setForm((f) => ({
        ...f,
        driver_id: f.driver_id || driverPage.items[0]?.id || "",
      }));
      setError(null);
    } catch {
      setError("We could not load the task board.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const byStatus = useMemo(() => {
    const groups: Record<string, Task[]> = {
      assigned: [],
      accepted: [],
      en_route: [],
      completed: [],
      cancelled: [],
    };
    for (const task of tasks) groups[task.status]?.push(task);
    return groups;
  }, [tasks]);

  async function runPreview() {
    if (!destination || !form.driver_id) return;
    setPreviewing(true);
    setPreviewNote(null);
    try {
      setPreview(
        await api.post<RoutePreview>("/tasks/route-preview", {
          driver_id: form.driver_id,
          destination_latitude: destination.lat,
          destination_longitude: destination.lng,
        }),
      );
    } catch (err) {
      setPreview(null);
      // Routing being down must not stop a dispatcher assigning work.
      setPreviewNote(
        err instanceof ApiError ? err.message : strings.tasks.routingUnavailable,
      );
    } finally {
      setPreviewing(false);
    }
  }

  async function createTask(event: FormEvent) {
    event.preventDefault();
    if (!destination) {
      setError(strings.tasks.pickOnMap);
      return;
    }
    setSaving(true);
    try {
      await api.post<Task>("/tasks", {
        title: form.title,
        description: form.description || null,
        task_type: form.task_type,
        priority: form.priority,
        driver_id: form.driver_id || null,
        destination_label: form.destination_label || null,
        destination_latitude: destination.lat,
        destination_longitude: destination.lng,
        due_at: form.due_at ? new Date(form.due_at).toISOString() : null,
      });
      setShowForm(false);
      setForm({ ...form, title: "", description: "", destination_label: "", due_at: "" });
      setDestination(null);
      setPreview(null);
      await load();
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We could not create that task.");
    } finally {
      setSaving(false);
    }
  }

  async function act(task: Task, action: string, body?: unknown) {
    try {
      await api.post(`/tasks/${task.id}/${action}`, body ?? {});
      setSelected(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That action did not work.");
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white">{strings.tasks.title}</h1>
          <p className="mt-1 text-sm text-ink-300">{strings.tasks.subtitle}</p>
        </div>
        <button onClick={() => setShowForm((o) => !o)} className="fb-button-primary">
          {showForm ? strings.common.cancel : strings.tasks.newTask}
        </button>
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      {showForm && (
        <form onSubmit={createTask} className="fb-card p-5">
          <div className="grid gap-5 lg:grid-cols-[1fr_20rem]">
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="space-y-1.5">
                  <span className="fb-label">Title</span>
                  <input
                    required
                    value={form.title}
                    onChange={(e) => setForm({ ...form, title: e.target.value })}
                    className="fb-input"
                    placeholder="Deliver pallet 42"
                  />
                </label>
                <label className="space-y-1.5">
                  <span className="fb-label">Driver</span>
                  <select
                    value={form.driver_id}
                    onChange={(e) => setForm({ ...form, driver_id: e.target.value })}
                    className="fb-input"
                  >
                    <option value="">{strings.tasks.unassigned}</option>
                    {drivers.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.full_name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="space-y-1.5">
                  <span className="fb-label">Type</span>
                  <select
                    value={form.task_type}
                    onChange={(e) => setForm({ ...form, task_type: e.target.value })}
                    className="fb-input"
                  >
                    {TASK_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t.replace("_", " ")}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="space-y-1.5">
                  <span className="fb-label">Priority</span>
                  <select
                    value={form.priority}
                    onChange={(e) => setForm({ ...form, priority: e.target.value })}
                    className="fb-input"
                  >
                    <option value="normal">Normal</option>
                    <option value="urgent">Urgent</option>
                  </select>
                </label>
                <label className="space-y-1.5">
                  <span className="fb-label">Destination name</span>
                  <input
                    value={form.destination_label}
                    onChange={(e) =>
                      setForm({ ...form, destination_label: e.target.value })
                    }
                    className="fb-input"
                    placeholder="Schiphol hub"
                  />
                </label>
                <label className="space-y-1.5">
                  <span className="fb-label">Due</span>
                  <input
                    type="datetime-local"
                    value={form.due_at}
                    onChange={(e) => setForm({ ...form, due_at: e.target.value })}
                    className="fb-input"
                  />
                </label>
              </div>

              <label className="block space-y-1.5">
                <span className="fb-label">Instructions</span>
                <textarea
                  rows={2}
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  className="fb-input"
                />
              </label>

              <div className="flex flex-wrap items-center gap-3">
                <button type="submit" disabled={saving} className="fb-button-primary">
                  {saving ? "Assigning…" : "Assign task"}
                </button>
                <button
                  type="button"
                  onClick={runPreview}
                  disabled={!destination || !form.driver_id || previewing}
                  className="fb-button-ghost"
                >
                  {previewing ? "Routing…" : strings.tasks.previewRoute}
                </button>
                {preview && (
                  <span className="fb-numeric text-xs text-ink-200">
                    {preview.distance_km.toFixed(1)} km ·{" "}
                    {Math.round(preview.duration_minutes)} min ·{" "}
                    {strings.tasks.eta}{" "}
                    {new Date(preview.eta).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                )}
              </div>

              {previewNote && (
                <p className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
                  {previewNote}
                </p>
              )}
            </div>

            <div className="space-y-2">
              <p className="fb-label">{strings.tasks.destination}</p>
              <div className="h-64 overflow-hidden rounded-lg border border-ink-600">
                <DestinationPicker
                  destination={destination}
                  onPick={(point) => {
                    setDestination(point);
                    setPreview(null);
                  }}
                  pois={pois}
                  routePolyline={preview?.geometry_polyline}
                />
              </div>
              <p className="fb-numeric text-[11px] text-ink-400">
                {destination
                  ? `${destination.lat.toFixed(5)}, ${destination.lng.toFixed(5)}`
                  : strings.tasks.pickOnMap}
              </p>
            </div>
          </div>
        </form>
      )}

      <div className="grid gap-3 lg:grid-cols-4">
        {COLUMNS.map((column) => (
          <section key={column.status} className="fb-card flex flex-col">
            <h2 className="flex items-center justify-between border-b border-ink-600/70 px-3 py-2.5 text-xs font-semibold uppercase tracking-wide text-ink-200">
              {column.label}
              <span className="fb-numeric rounded bg-ink-700 px-1.5 py-0.5 text-[10px] text-ink-300">
                {byStatus[column.status].length}
              </span>
            </h2>
            <ul className="min-h-24 flex-1 space-y-2 p-2">
              {loading ? (
                <li className="px-2 py-3 text-xs text-ink-400">
                  {strings.common.loading}
                </li>
              ) : byStatus[column.status].length === 0 ? (
                <li className="px-2 py-3 text-xs text-ink-500">
                  {strings.tasks.noTasks}
                </li>
              ) : (
                byStatus[column.status].map((task) => (
                  <li key={task.id}>
                    <button
                      onClick={() => setSelected(task)}
                      className="w-full rounded-lg border border-ink-600/70 bg-ink-900/50 p-3 text-left transition hover:border-electric/50"
                    >
                      <span className="flex items-start justify-between gap-2">
                        <span className="text-xs font-medium text-ink-50">
                          {task.title}
                        </span>
                        {task.priority === "urgent" && (
                          <span className="fb-badge shrink-0 bg-coral/15 text-coral">
                            Urgent
                          </span>
                        )}
                      </span>
                      <span className="mt-1 block truncate text-[11px] text-ink-400">
                        {task.driver_name ?? strings.tasks.unassigned}
                        {task.destination_label && ` → ${task.destination_label}`}
                      </span>
                      {(task.eta || task.due_at) && (
                        <span className="fb-numeric mt-1 block text-[10px] text-ink-500">
                          {task.eta
                            ? `${strings.tasks.eta} ${new Date(task.eta).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
                            : `${strings.tasks.due} ${new Date(task.due_at as string).toLocaleString()}`}
                        </span>
                      )}
                    </button>
                  </li>
                ))
              )}
            </ul>
          </section>
        ))}
      </div>

      {byStatus.cancelled.length > 0 && (
        <section className="fb-card">
          <h2 className="border-b border-ink-600/70 px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-ink-400">
            {strings.tasks.cancelled} ({byStatus.cancelled.length})
          </h2>
          <ul className="divide-y divide-ink-600/50">
            {byStatus.cancelled.map((task) => (
              <li key={task.id} className="px-4 py-2.5 text-xs text-ink-400">
                <span className="text-ink-300">{task.title}</span>
                {task.cancellation_reason && ` — ${task.cancellation_reason}`}
              </li>
            ))}
          </ul>
        </section>
      )}

      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/70 p-4">
          <div className="fb-card w-full max-w-lg p-6">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-white">
                  {selected.title}
                </h2>
                <p className="mt-0.5 text-xs text-ink-400">
                  {selected.task_type.replace("_", " ")} · {selected.status.replace("_", " ")}
                </p>
              </div>
              <button
                onClick={() => setSelected(null)}
                aria-label="Close"
                className="rounded p-1 text-ink-400 hover:bg-ink-700 hover:text-white"
              >
                ×
              </button>
            </div>

            <dl className="mt-4 space-y-2 text-xs">
              <Row label="Driver" value={selected.driver_name ?? strings.tasks.unassigned} />
              <Row label="Vehicle" value={selected.vehicle_name ?? "—"} />
              <Row
                label={strings.tasks.destination}
                value={
                  selected.destination_label ??
                  `${selected.destination_latitude.toFixed(4)}, ${selected.destination_longitude.toFixed(4)}`
                }
              />
              <Row
                label={strings.tasks.eta}
                value={selected.eta ? new Date(selected.eta).toLocaleString() : "—"}
              />
              {selected.completion_note && (
                <Row label="Completion note" value={selected.completion_note} />
              )}
            </dl>

            {selected.description && (
              <p className="mt-4 rounded border border-ink-600 px-3 py-2 text-xs leading-relaxed text-ink-300">
                {selected.description}
              </p>
            )}

            <div className="mt-5 flex flex-wrap gap-2">
              {selected.status === "assigned" && (
                <select
                  onChange={(e) =>
                    e.target.value &&
                    act(selected, "reassign", { driver_id: e.target.value })
                  }
                  defaultValue=""
                  className="fb-input !w-auto !py-1.5 text-xs"
                >
                  <option value="">{strings.tasks.reassign}…</option>
                  {drivers
                    .filter((d) => d.id !== selected.driver_id)
                    .map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.full_name}
                      </option>
                    ))}
                </select>
              )}
              {selected.status === "en_route" && (
                <button
                  onClick={() => act(selected, "complete")}
                  className="fb-button-primary !py-1.5 text-xs"
                >
                  {strings.tasks.complete}
                </button>
              )}
              {!["completed", "cancelled"].includes(selected.status) && (
                <button
                  onClick={() =>
                    act(selected, "cancel", {
                      reason: window.prompt("Why is this task cancelled?") ?? null,
                    })
                  }
                  className="fb-button-danger !py-1.5 text-xs"
                >
                  {strings.tasks.cancel}
                </button>
              )}
            </div>
          </div>
        </div>
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
