"use client";

/**
 * Sign-in activity and known devices (Section 7).
 *
 * Detection already happens on every login - a sign-in from a device we have
 * not seen raises an alert. This screen is where an admin reads that history
 * back, which is the half that was missing.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import type {
  KnownDevice,
  LoginAttempt,
  Page,
  SecurityOverview,
} from "@/lib/types";
import { Pager } from "@/components/Pager";
import { StatTile } from "@/components/charts/StatTile";

const PAGE_SIZE = 50;

export default function SecurityPage() {
  const { session } = useSession();
  const [overview, setOverview] = useState<SecurityOverview | null>(null);
  const [attempts, setAttempts] = useState<LoginAttempt[]>([]);
  const [devices, setDevices] = useState<KnownDevice[]>([]);
  const [suspiciousOnly, setSuspiciousOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const isAdmin = session?.user.role === "org_admin";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (suspiciousOnly) params.set("suspicious_only", "true");

      const [summary, page, deviceList] = await Promise.all([
        api.get<SecurityOverview>("/security/overview"),
        api.get<Page<LoginAttempt>>(`/security/login-activity?${params}`),
        api.get<KnownDevice[]>("/security/known-devices"),
      ]);
      setOverview(summary);
      setAttempts(page.items);
      setTotal(page.total);
      setDevices(deviceList);
      setError(null);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? "Only an organisation admin can read sign-in activity."
          : "We could not load sign-in activity.",
      );
    } finally {
      setLoading(false);
    }
  }, [offset, suspiciousOnly]);

  useEffect(() => {
    if (!isAdmin) {
      setLoading(false);
      return;
    }
    void load();
  }, [load, isAdmin]);

  if (!isAdmin) {
    return (
      <p className="fb-card text-sm text-ink-300">
        Only an organisation admin can read sign-in activity.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-white">{strings.security.title}</h1>
        <p className="mt-1 text-sm text-ink-300">{strings.security.subtitle}</p>
      </div>

      {error && (
        <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label={strings.security.suspicious7d}
          value={overview?.suspicious_logins_7d ?? "—"}
          tone={overview && overview.suspicious_logins_7d > 0 ? "critical" : "neutral"}
        />
        <StatTile
          label={strings.security.failed7d}
          value={overview?.failed_logins_7d ?? "—"}
        />
        <StatTile
          label={strings.security.lockedAccounts}
          value={overview?.locked_accounts ?? "—"}
          hint={strings.security.lockoutNote}
        />
        <StatTile
          label={strings.security.noKnownDevice}
          value={overview?.users_without_a_known_device ?? "—"}
        />
      </div>

      <section className="fb-card !p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-600/70 px-4 py-3">
          <h2 className="text-sm font-semibold text-white">
            {strings.security.activityTitle}
          </h2>
          <label className="flex cursor-pointer items-center gap-2 text-xs text-ink-200">
            <input
              type="checkbox"
              checked={suspiciousOnly}
              onChange={(event) => {
                setOffset(0);
                setSuspiciousOnly(event.target.checked);
              }}
              className="h-3.5 w-3.5 accent-electric"
            />
            {strings.security.suspiciousOnly}
          </label>
        </div>

        {loading ? (
          <p className="px-4 py-6 text-sm text-ink-400">{strings.common.loading}</p>
        ) : attempts.length === 0 ? (
          <p className="px-4 py-6 text-sm text-ink-400">
            {strings.security.activityEmpty}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm" style={{ minWidth: "44rem" }}>
              <thead className="border-b border-ink-600/70 text-xs uppercase tracking-wide text-ink-400">
                <tr>
                  <th scope="col" className="px-4 py-2.5 font-medium">
                    {strings.audit.when}
                  </th>
                  <th scope="col" className="px-4 py-2.5 font-medium">
                    {strings.audit.who}
                  </th>
                  <th scope="col" className="px-4 py-2.5 font-medium">
                    Result
                  </th>
                  <th scope="col" className="px-4 py-2.5 font-medium">
                    IP
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-600/50">
                {attempts.map((attempt) => (
                  <tr key={attempt.id} className="hover:bg-ink-700/40">
                    <td className="fb-numeric whitespace-nowrap px-4 py-2.5 text-xs text-ink-300">
                      {new Date(attempt.attempted_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-ink-100">
                      {attempt.email}
                    </td>
                    <td className="px-4 py-2.5">
                      <span
                        className={`fb-badge ${
                          attempt.suspicious
                            ? "bg-coral/15 text-coral"
                            : attempt.successful
                              ? "bg-success/15 text-success"
                              : "bg-warning/15 text-warning"
                        }`}
                      >
                        {attempt.suspicious
                          ? strings.security.flagged
                          : attempt.successful
                            ? strings.security.succeeded
                            : strings.security.failed}
                      </span>
                      {attempt.suspicion_reason && (
                        <span className="mt-1 block text-[11px] text-ink-400">
                          {attempt.suspicion_reason}
                        </span>
                      )}
                    </td>
                    <td className="fb-numeric px-4 py-2.5 text-xs text-ink-300">
                      {attempt.ip_address ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="border-t border-ink-600/70 px-4 py-3">
          <Pager
            offset={offset}
            total={total}
            pageSize={PAGE_SIZE}
            onChange={setOffset}
          />
        </div>
      </section>

      <section className="fb-card">
        <h2 className="text-sm font-semibold text-white">
          {strings.security.devicesTitle}
        </h2>
        <p className="mt-1 text-[11px] text-ink-400">{strings.security.devicesHint}</p>

        {devices.length === 0 ? (
          <p className="mt-3 text-xs text-ink-400">{strings.security.devicesEmpty}</p>
        ) : (
          <ul className="mt-3 divide-y divide-ink-700/60">
            {devices.map((device) => (
              <li
                key={device.id}
                className="flex flex-wrap items-center justify-between gap-2 py-2"
              >
                <span className="text-xs text-ink-100">
                  {device.label ?? "Unlabelled device"}
                </span>
                <span className="fb-numeric text-[11px] text-ink-400">
                  {device.last_ip ?? "—"} ·{" "}
                  {device.last_seen_at
                    ? `${strings.security.lastSeen} ${new Date(
                        device.last_seen_at,
                      ).toLocaleString()}`
                    : "—"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
