"use client";

/**
 * GPS device inventory (Section 4a item 2) - platform staff only.
 *
 * This is where hardware enters stock, gets fitted to a customer's vehicle,
 * and goes live. Assigning an active device is what makes a vehicle appear as
 * tracked in that customer's dashboard; until then it shows as "Not Tracked".
 */

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError, api } from "@/lib/api";
import { strings } from "@/lib/strings";
import type { DeviceStatus, OrganizationHealth, Page, PlatformDevice } from "@/lib/types";

interface OrgVehicle {
  id: string;
  name: string;
  license_plate: string;
}

const STATUS_STYLES: Record<DeviceStatus, string> = {
  in_stock: "bg-ink-100 text-ink-600",
  assigned: "bg-electric/10 text-electric-700",
  active: "bg-success/10 text-success",
  faulty: "bg-danger/10 text-danger",
  retired: "bg-ink-100 text-ink-400",
};

export default function DevicesPage() {
  const [devices, setDevices] = useState<PlatformDevice[]>([]);
  const [organizations, setOrganizations] = useState<OrganizationHealth[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<DeviceStatus | "">("");

  const [serial, setSerial] = useState("");
  const [imei, setImei] = useState("");
  const [model, setModel] = useState("");
  const [adding, setAdding] = useState(false);

  const [assigning, setAssigning] = useState<PlatformDevice | null>(null);
  const [assignOrg, setAssignOrg] = useState("");
  const [assignVehicle, setAssignVehicle] = useState("");
  const [orgVehicles, setOrgVehicles] = useState<OrgVehicle[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const query = new URLSearchParams({ limit: "200" });
      if (search.trim()) query.set("search", search.trim());
      if (statusFilter) query.set("status", statusFilter);

      const [devicePage, orgRows] = await Promise.all([
        api.get<Page<PlatformDevice>>(`/platform-admin/devices?${query}`),
        api.get<OrganizationHealth[]>("/platform-admin/organizations"),
      ]);
      setDevices(devicePage.items);
      setOrganizations(orgRows);
      setError(null);
    } catch {
      setError("We could not load the device inventory.");
    } finally {
      setLoading(false);
    }
  }, [search, statusFilter]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 250);
    return () => clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    if (!assignOrg) {
      setOrgVehicles([]);
      return;
    }
    api
      .get<OrgVehicle[]>(`/platform-admin/organizations/${assignOrg}/vehicles`)
      .then((rows) => {
        setOrgVehicles(rows);
        setAssignVehicle(rows[0]?.id ?? "");
      })
      .catch(() => setOrgVehicles([]));
  }, [assignOrg]);

  async function addDevice(event: FormEvent) {
    event.preventDefault();
    setAdding(true);
    try {
      await api.post("/platform-admin/devices", {
        serial_number: serial,
        imei: imei || null,
        model: model || null,
      });
      setSerial("");
      setImei("");
      setModel("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We could not add that device.");
    } finally {
      setAdding(false);
    }
  }

  async function confirmAssign() {
    if (!assigning || !assignOrg || !assignVehicle) return;
    try {
      await api.post(`/platform-admin/devices/${assigning.id}/assign`, {
        organization_id: assignOrg,
        vehicle_id: assignVehicle,
        activate: true,
      });
      setAssigning(null);
      setAssignOrg("");
      setAssignVehicle("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We could not fit that device.");
    }
  }

  async function unassign(device: PlatformDevice) {
    if (
      !window.confirm(
        `Remove ${device.serial_number} from ${device.vehicle_name ?? "its vehicle"}? ` +
          "The vehicle will stop being tracked.",
      )
    ) {
      return;
    }
    try {
      await api.post(`/platform-admin/devices/${device.id}/unassign`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That did not work.");
    }
  }

  async function setStatus(device: PlatformDevice, status: DeviceStatus) {
    try {
      await api.patch(`/platform-admin/devices/${device.id}/status`, { status });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That did not work.");
    }
  }

  const counts = devices.reduce<Record<string, number>>((acc, device) => {
    acc[device.status] = (acc[device.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-ink-900">{strings.platform.devices}</h1>
        <p className="mt-1 text-sm text-ink-400">
          FleetBeat owns and fits every GPS device. Customers see device status
          read-only and cannot change any of this.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {(["in_stock", "assigned", "active", "faulty", "retired"] as const).map(
          (status) => (
            <button
              key={status}
              onClick={() => setStatusFilter(statusFilter === status ? "" : status)}
              className={`rounded-xl border px-4 py-3 text-left transition ${
                statusFilter === status
                  ? "border-electric bg-electric/5"
                  : "border-ink-200 bg-white hover:border-ink-300"
              }`}
            >
              <p className="text-xs font-medium uppercase tracking-wider text-ink-400">
                {status.replace("_", " ")}
              </p>
              <p className="fb-numeric mt-1 text-2xl font-semibold text-ink-900">
                {counts[status] ?? 0}
              </p>
            </button>
          ),
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      <form
        onSubmit={addDevice}
        className="flex flex-wrap items-end gap-3 rounded-xl border border-ink-200 bg-white p-4"
      >
        <label className="space-y-1.5">
          <span className="block text-xs font-medium uppercase tracking-wider text-ink-400">
            Serial number
          </span>
          <input
            required
            value={serial}
            onChange={(e) => setSerial(e.target.value)}
            className="light-input"
            placeholder="FB-00123"
          />
        </label>
        <label className="space-y-1.5">
          <span className="block text-xs font-medium uppercase tracking-wider text-ink-400">
            IMEI
          </span>
          <input
            value={imei}
            onChange={(e) => setImei(e.target.value)}
            className="light-input"
          />
        </label>
        <label className="space-y-1.5">
          <span className="block text-xs font-medium uppercase tracking-wider text-ink-400">
            Model
          </span>
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="light-input"
          />
        </label>
        <button type="submit" disabled={adding} className="fb-button-primary">
          {adding ? "Adding…" : "Add to inventory"}
        </button>
      </form>

      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search serial, IMEI or model"
        aria-label={strings.common.search}
        className="light-input max-w-sm"
      />

      <section className="overflow-x-auto rounded-xl border border-ink-200 bg-white">
        {loading ? (
          <p className="px-4 py-6 text-sm text-ink-400">{strings.common.loading}</p>
        ) : devices.length === 0 ? (
          <p className="px-4 py-6 text-sm text-ink-400">
            No devices match. Add hardware as it arrives.
          </p>
        ) : (
          <table className="w-full min-w-[52rem] text-left text-sm">
            <thead className="border-b border-ink-200 text-xs uppercase tracking-wide text-ink-400">
              <tr>
                <th className="px-4 py-2.5 font-medium">Serial</th>
                <th className="px-4 py-2.5 font-medium">Model</th>
                <th className="px-4 py-2.5 font-medium">Organization</th>
                <th className="px-4 py-2.5 font-medium">Vehicle</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium" />
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {devices.map((device) => (
                <tr key={device.id} className="hover:bg-ink-50">
                  <td className="px-4 py-3 font-mono text-xs text-ink-900">
                    {device.serial_number}
                  </td>
                  <td className="px-4 py-3 text-ink-600">{device.model ?? "—"}</td>
                  <td className="px-4 py-3 text-ink-600">
                    {device.organization_name ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-ink-600">
                    {device.vehicle_name
                      ? `${device.vehicle_name} (${device.vehicle_plate})`
                      : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`fb-badge ${STATUS_STYLES[device.status]}`}>
                      {device.status.replace("_", " ")}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-3 text-xs">
                      {device.vehicle_id ? (
                        <button
                          onClick={() => unassign(device)}
                          className="text-ink-500 hover:text-ink-900"
                        >
                          Unassign
                        </button>
                      ) : (
                        device.status !== "retired" && (
                          <button
                            onClick={() => {
                              setAssigning(device);
                              setAssignOrg(organizations[0]?.organization.id ?? "");
                            }}
                            className="text-electric-600 hover:text-electric-700"
                          >
                            Fit to vehicle
                          </button>
                        )
                      )}
                      {device.status !== "faulty" && (
                        <button
                          onClick={() => setStatus(device, "faulty")}
                          className="text-danger hover:underline"
                        >
                          Faulty
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {assigning && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/60 p-4">
          <div className="w-full max-w-md rounded-xl border border-ink-200 bg-white p-6">
            <h2 className="text-base font-semibold text-ink-900">
              Fit {assigning.serial_number}
            </h2>
            <p className="mt-1 text-xs text-ink-400">
              The vehicle goes live as soon as this is saved.
            </p>

            <div className="mt-5 space-y-4">
              <label className="block space-y-1.5">
                <span className="block text-xs font-medium uppercase tracking-wider text-ink-400">
                  Organization
                </span>
                <select
                  value={assignOrg}
                  onChange={(e) => setAssignOrg(e.target.value)}
                  className="light-input"
                >
                  {organizations.map((row) => (
                    <option key={row.organization.id} value={row.organization.id}>
                      {row.organization.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block space-y-1.5">
                <span className="block text-xs font-medium uppercase tracking-wider text-ink-400">
                  Vehicle
                </span>
                <select
                  value={assignVehicle}
                  onChange={(e) => setAssignVehicle(e.target.value)}
                  className="light-input"
                  disabled={orgVehicles.length === 0}
                >
                  {orgVehicles.map((vehicle) => (
                    <option key={vehicle.id} value={vehicle.id}>
                      {vehicle.name} · {vehicle.license_plate}
                    </option>
                  ))}
                </select>
                {orgVehicles.length === 0 && (
                  <span className="text-xs text-warning">
                    That organization has no vehicles yet.
                  </span>
                )}
              </label>
            </div>

            <div className="mt-6 flex gap-2">
              <button
                onClick={confirmAssign}
                disabled={!assignVehicle}
                className="fb-button-primary"
              >
                Fit and activate
              </button>
              <button
                onClick={() => setAssigning(null)}
                className="fb-button rounded-lg border border-ink-200 text-ink-700 hover:bg-ink-50"
              >
                {strings.common.cancel}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
