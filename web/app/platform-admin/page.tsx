"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ApiError, api, tokenStore } from "@/lib/api";
import { useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import type {
  OrganizationHealth,
  PlatformOverview,
  Session,
} from "@/lib/types";

/** Organization list - the Platform Admin Console's landing page. */
export default function PlatformOrganizationsPage() {
  const router = useRouter();
  const { refresh } = useSession();

  const [rows, setRows] = useState<OrganizationHealth[]>([]);
  const [overview, setOverview] = useState<PlatformOverview | null>(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async (term: string) => {
    setLoading(true);
    try {
      const query = term.trim()
        ? `?search=${encodeURIComponent(term.trim())}`
        : "";
      const [organizations, summary] = await Promise.all([
        api.get<OrganizationHealth[]>(`/platform-admin/organizations${query}`),
        api.get<PlatformOverview>("/platform-admin/overview"),
      ]);
      setRows(organizations);
      setOverview(summary);
      setError(null);
    } catch {
      setError("We could not load the organization list.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void load(search), 250);
    return () => clearTimeout(timer);
  }, [search, load]);

  async function toggleStatus(row: OrganizationHealth) {
    const suspending = row.organization.status === "active";
    setBusyId(row.organization.id);
    try {
      await api.post(
        `/platform-admin/organizations/${row.organization.id}/${
          suspending ? "suspend" : "reactivate"
        }`,
      );
      await load(search);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That did not work.");
    } finally {
      setBusyId(null);
    }
  }

  async function impersonate(row: OrganizationHealth) {
    setBusyId(row.organization.id);
    try {
      const result = await api.post<{ tokens: Session["tokens"] }>(
        `/platform-admin/organizations/${row.organization.id}/impersonate`,
      );
      // Swap this browser session for the customer's - every impersonation
      // is written to the audit log server-side (Section 4a item 3).
      tokenStore.write(result.tokens);
      await refresh();
      router.push("/dashboard");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "We could not open that account.",
      );
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink-900">
            {strings.platform.organizations}
          </h1>
          <p className="mt-1 text-sm text-ink-400">
            {strings.platform.subtitle}
          </p>
        </div>
        <Link href="/platform-admin/organizations/new" className="fb-button-primary">
          {strings.platform.newOrganization}
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Organizations" value={overview?.total_organizations} />
        <Stat label="Active" value={overview?.active_organizations} />
        <Stat label="Vehicles" value={overview?.total_vehicles} />
        <Stat label="Active devices" value={overview?.active_devices} />
        <Stat label="Devices in stock" value={overview?.devices_in_stock} />
      </div>

      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full max-w-sm rounded-lg border border-ink-200 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none focus:border-electric focus:ring-2 focus:ring-electric/20"
        placeholder="Search organizations"
        aria-label={strings.common.search}
      />

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      <section className="overflow-x-auto rounded-xl border border-ink-200 bg-white">
        {loading ? (
          <p className="px-4 py-6 text-sm text-ink-400">
            {strings.common.loading}
          </p>
        ) : rows.length === 0 ? (
          <p className="px-4 py-6 text-sm text-ink-400">
            No organizations yet. Provision the first one to get started.
          </p>
        ) : (
          <table className="w-full min-w-[54rem] text-left text-sm">
            <thead className="border-b border-ink-200 text-xs uppercase tracking-wide text-ink-400">
              <tr>
                <th className="px-4 py-2.5 font-medium">Organization</th>
                <th className="px-4 py-2.5 font-medium">Vehicles</th>
                <th className="px-4 py-2.5 font-medium">Active devices</th>
                <th className="px-4 py-2.5 font-medium">Users</th>
                <th className="px-4 py-2.5 font-medium">Last login</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium" />
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {rows.map((row) => (
                <tr key={row.organization.id} className="hover:bg-ink-50">
                  <td className="px-4 py-3">
                    <span className="font-medium text-ink-900">
                      {row.organization.name}
                    </span>
                    <span className="block text-xs text-ink-400">
                      {row.organization.industry ?? "—"} ·{" "}
                      {row.organization.timezone}
                    </span>
                  </td>
                  <td className="fb-numeric px-4 py-3 text-ink-700">
                    {row.vehicle_count}
                  </td>
                  <td className="fb-numeric px-4 py-3 text-ink-700">
                    {row.active_device_count}
                  </td>
                  <td className="fb-numeric px-4 py-3 text-ink-700">
                    {row.user_count}
                  </td>
                  <td className="px-4 py-3 text-xs text-ink-400">
                    {row.last_login_at
                      ? new Date(row.last_login_at).toLocaleDateString()
                      : "Never"}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`fb-badge ${
                        row.organization.status === "active"
                          ? "bg-success/10 text-success"
                          : "bg-danger/10 text-danger"
                      }`}
                    >
                      {row.organization.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => impersonate(row)}
                        disabled={
                          busyId === row.organization.id ||
                          row.organization.status !== "active"
                        }
                        className="fb-button rounded-lg border border-ink-200 !px-3 !py-1.5 text-xs text-ink-700 hover:bg-ink-50"
                      >
                        {strings.platform.impersonate}
                      </button>
                      <button
                        onClick={() => toggleStatus(row)}
                        disabled={busyId === row.organization.id}
                        className={`fb-button rounded-lg !px-3 !py-1.5 text-xs ${
                          row.organization.status === "active"
                            ? "border border-danger/30 text-danger hover:bg-danger/5"
                            : "border border-success/30 text-success hover:bg-success/5"
                        }`}
                      >
                        {row.organization.status === "active"
                          ? strings.platform.suspend
                          : strings.platform.reactivate}
                      </button>
                    </div>
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

function Stat({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="rounded-xl border border-ink-200 bg-white px-4 py-3">
      <p className="text-xs font-medium uppercase tracking-wider text-ink-400">
        {label}
      </p>
      <p className="fb-numeric mt-1 text-2xl font-semibold text-ink-900">
        {value ?? "—"}
      </p>
    </div>
  );
}
