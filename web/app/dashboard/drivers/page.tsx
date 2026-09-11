"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import type { Driver, Page } from "@/lib/types";

interface DriverCreateResponse {
  driver: Driver;
  activation_url: string | null;
}

export default function DriversPage() {
  const { session } = useSession();
  const canEdit = session?.user.role === "org_admin";

  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [fullName, setFullName] = useState("");
  const [licenseNumber, setLicenseNumber] = useState("");
  const [loginEmail, setLoginEmail] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [activationUrl, setActivationUrl] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setDrivers((await api.get<Page<Driver>>("/drivers?limit=200")).items);
      setError(null);
    } catch {
      setError("We could not load your drivers.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      const result = await api.post<DriverCreateResponse>("/drivers", {
        full_name: fullName,
        license_number: licenseNumber || null,
        login_email: loginEmail || null,
      });
      // The activation link is shown for manual delivery - no email provider
      // is integrated in this phase (Section 4a).
      setActivationUrl(result.activation_url);
      setFullName("");
      setLicenseNumber("");
      setLoginEmail("");
      setShowForm(false);
      await load();
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "We could not save that driver.",
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
            {strings.dashboard.driversTitle}
          </h1>
          <p className="mt-1 text-sm text-ink-300">
            Driver profiles, licences and mobile-app access.
          </p>
        </div>
        {canEdit && (
          <button
            onClick={() => setShowForm((open) => !open)}
            className="fb-button-primary"
          >
            {showForm ? strings.common.cancel : "Add driver"}
          </button>
        )}
      </div>

      {activationUrl && (
        <ActivationLinkCard
          url={activationUrl}
          onDismiss={() => setActivationUrl(null)}
        />
      )}

      {showForm && canEdit && (
        <form onSubmit={handleCreate} className="fb-card space-y-4 p-5">
          <div className="grid gap-4 sm:grid-cols-3">
            <label className="space-y-1.5">
              <span className="fb-label">
                Full name<span className="ml-1 text-coral">*</span>
              </span>
              <input
                required
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="fb-input"
              />
            </label>
            <label className="space-y-1.5">
              <span className="fb-label">Licence number</span>
              <input
                value={licenseNumber}
                onChange={(e) => setLicenseNumber(e.target.value)}
                className="fb-input"
              />
            </label>
            <label className="space-y-1.5">
              <span className="fb-label">Mobile app email</span>
              <input
                type="email"
                value={loginEmail}
                onChange={(e) => setLoginEmail(e.target.value)}
                className="fb-input"
                placeholder="Optional"
              />
            </label>
          </div>

          {formError && (
            <p role="alert" className="text-sm text-danger">
              {formError}
            </p>
          )}

          <button type="submit" disabled={saving} className="fb-button-primary">
            {saving ? "Saving…" : strings.common.save}
          </button>
        </form>
      )}

      <section className="fb-card overflow-x-auto">
        {error ? (
          <p className="px-4 py-6 text-sm text-danger">{error}</p>
        ) : loading ? (
          <p className="px-4 py-6 text-sm text-ink-400">
            {strings.common.loading}
          </p>
        ) : drivers.length === 0 ? (
          <p className="px-4 py-6 text-sm text-ink-400">
            {strings.common.empty}
          </p>
        ) : (
          <table className="w-full min-w-[40rem] text-left text-sm">
            <thead className="border-b border-ink-600/70 text-xs uppercase tracking-wide text-ink-400">
              <tr>
                <th className="px-4 py-2.5 font-medium">Driver</th>
                <th className="px-4 py-2.5 font-medium">Licence</th>
                <th className="px-4 py-2.5 font-medium">Employment</th>
                <th className="px-4 py-2.5 font-medium">Safety score</th>
                <th className="px-4 py-2.5 font-medium">Points</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-600/50">
              {drivers.map((driver) => (
                <tr key={driver.id} className="hover:bg-ink-700/40">
                  <td className="px-4 py-3 font-medium text-ink-50">
                    {driver.full_name}
                  </td>
                  <td className="px-4 py-3 text-ink-300">
                    {driver.license_number ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-ink-300">
                    {driver.employment_status}
                  </td>
                  <td className="fb-numeric px-4 py-3 text-ink-200">
                    {Math.round(driver.safety_score)}
                  </td>
                  <td className="fb-numeric px-4 py-3 text-ink-200">
                    {driver.points_balance}
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

function ActivationLinkCard({
  url,
  onDismiss,
}: {
  url: string;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);

  return (
    <div className="fb-card space-y-3 border-electric/40 bg-electric/5 p-5">
      <div>
        <p className="text-sm font-semibold text-white">Driver invited</p>
        <p className="mt-1 text-xs text-ink-300">
          {strings.platform.activationHint}
        </p>
      </div>
      <code className="block break-all rounded-lg bg-ink-900/70 px-3 py-2 font-mono text-xs text-electric-200">
        {url}
      </code>
      <div className="flex gap-2">
        <button
          onClick={async () => {
            await navigator.clipboard.writeText(url);
            setCopied(true);
          }}
          className="fb-button-primary !py-1.5"
        >
          {copied ? strings.platform.copied : strings.platform.copyLink}
        </button>
        <button onClick={onDismiss} className="fb-button-ghost !py-1.5">
          Dismiss
        </button>
      </div>
    </div>
  );
}
