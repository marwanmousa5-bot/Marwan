"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";

import { ApiError, api } from "@/lib/api";
import { strings } from "@/lib/strings";
import type { OrganizationProvisionResult } from "@/lib/types";

const TIMEZONES = [
  "UTC",
  "Europe/London",
  "Europe/Amsterdam",
  "Europe/Berlin",
  "Africa/Cairo",
  "Asia/Dubai",
  "Asia/Riyadh",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
];

const EMPTY = {
  name: "",
  industry: "",
  timezone: "UTC",
  contact_name: "",
  contact_email: "",
  contact_phone: "",
  admin_full_name: "",
  admin_email: "",
};

/**
 * The ONLY path by which a customer organization comes into existence
 * (Section 4a item 1). This flow is used constantly by the onboarding team,
 * so it is one screen with no wizard steps and no optional detours.
 */
export default function ProvisionOrganizationPage() {
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OrganizationProvisionResult | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      setResult(
        await api.post<OrganizationProvisionResult>(
          "/platform-admin/organizations",
          {
            name: form.name,
            industry: form.industry || null,
            timezone: form.timezone,
            contact_name: form.contact_name || null,
            contact_email: form.contact_email || null,
            contact_phone: form.contact_phone || null,
            admin_full_name: form.admin_full_name,
            admin_email: form.admin_email,
          },
        ),
      );
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "We could not create that organization.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (result) {
    return (
      <div className="mx-auto max-w-2xl space-y-5">
        <div className="rounded-xl border border-success/30 bg-success/5 p-6">
          <h1 className="text-lg font-semibold text-ink-900">
            {strings.platform.activationReady}
          </h1>
          <p className="mt-1 text-sm text-ink-600">
            <strong>{result.organization.name}</strong> is live, with{" "}
            <strong>{result.admin_user.full_name}</strong> (
            {result.admin_user.email}) as its administrator.
          </p>

          <div className="mt-5 rounded-lg border border-ink-200 bg-white p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-ink-400">
              One-time activation link
            </p>
            <p className="mt-1 text-xs text-ink-500">
              {strings.platform.activationHint}
            </p>
            <code className="mt-3 block break-all rounded-lg bg-ink-50 px-3 py-2 font-mono text-xs text-electric-700">
              {result.activation_url}
            </code>
            <button
              onClick={async () => {
                await navigator.clipboard.writeText(result.activation_url);
                setCopied(true);
              }}
              className="fb-button-primary mt-3 !py-1.5"
            >
              {copied ? strings.platform.copied : strings.platform.copyLink}
            </button>
          </div>
        </div>

        <div className="flex gap-2">
          <Link href="/platform-admin" className="fb-button-primary">
            Back to organizations
          </Link>
          <button
            onClick={() => {
              setResult(null);
              setForm(EMPTY);
              setCopied(false);
            }}
            className="fb-button rounded-lg border border-ink-200 text-ink-700 hover:bg-ink-50"
          >
            Provision another
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-ink-900">
          {strings.platform.provisionTitle}
        </h1>
        <p className="mt-1 text-sm text-ink-400">
          {strings.platform.provisionIntro}
        </p>
      </div>

      <form
        onSubmit={handleSubmit}
        className="space-y-6 rounded-xl border border-ink-200 bg-white p-6"
      >
        <fieldset className="space-y-4">
          <legend className="text-sm font-semibold text-ink-900">
            Organization
          </legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <LightField label="Name" required>
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="light-input"
                placeholder="Northwind Transport"
              />
            </LightField>
            <LightField label="Industry">
              <input
                value={form.industry}
                onChange={(e) => setForm({ ...form, industry: e.target.value })}
                className="light-input"
                placeholder="Logistics"
              />
            </LightField>
            <LightField label="Timezone" required>
              <select
                value={form.timezone}
                onChange={(e) => setForm({ ...form, timezone: e.target.value })}
                className="light-input"
              >
                {TIMEZONES.map((tz) => (
                  <option key={tz} value={tz}>
                    {tz}
                  </option>
                ))}
              </select>
            </LightField>
            <LightField label="Contact name">
              <input
                value={form.contact_name}
                onChange={(e) =>
                  setForm({ ...form, contact_name: e.target.value })
                }
                className="light-input"
              />
            </LightField>
            <LightField label="Contact email">
              <input
                type="email"
                value={form.contact_email}
                onChange={(e) =>
                  setForm({ ...form, contact_email: e.target.value })
                }
                className="light-input"
              />
            </LightField>
            <LightField label="Contact phone">
              <input
                value={form.contact_phone}
                onChange={(e) =>
                  setForm({ ...form, contact_phone: e.target.value })
                }
                className="light-input"
              />
            </LightField>
          </div>
        </fieldset>

        <fieldset className="space-y-4 border-t border-ink-100 pt-6">
          <legend className="text-sm font-semibold text-ink-900">
            First administrator
          </legend>
          <p className="text-xs text-ink-400">
            This account is created in a pending state. It becomes usable once
            they open the activation link and set a password.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <LightField label="Full name" required>
              <input
                required
                value={form.admin_full_name}
                onChange={(e) =>
                  setForm({ ...form, admin_full_name: e.target.value })
                }
                className="light-input"
              />
            </LightField>
            <LightField label="Email" required>
              <input
                required
                type="email"
                value={form.admin_email}
                onChange={(e) =>
                  setForm({ ...form, admin_email: e.target.value })
                }
                className="light-input"
              />
            </LightField>
          </div>
        </fieldset>

        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}

        <div className="flex gap-2 border-t border-ink-100 pt-5">
          <button type="submit" disabled={saving} className="fb-button-primary">
            {saving ? "Creating…" : "Create organization"}
          </button>
          <Link
            href="/platform-admin"
            className="fb-button rounded-lg border border-ink-200 text-ink-700 hover:bg-ink-50"
          >
            {strings.common.cancel}
          </Link>
        </div>
      </form>
    </div>
  );
}

function LightField({
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
      <span className="block text-xs font-medium uppercase tracking-wider text-ink-400">
        {label}
        {required && <span className="ml-1 text-coral">*</span>}
      </span>
      {children}
    </label>
  );
}
