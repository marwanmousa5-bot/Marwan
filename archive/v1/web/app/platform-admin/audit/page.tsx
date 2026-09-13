"use client";

/**
 * Platform-wide audit trail - `super_admin` only (Sections 4a, 4.18).
 *
 * This is the view a customer admin can never reach: every tenant's actions
 * plus the platform-level events that belong to no tenant at all
 * (provisioning, suspension, impersonation).
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { strings } from "@/lib/strings";
import type { AuditEntry, OrganizationHealth, Page } from "@/lib/types";
import { AuditTable } from "@/components/audit/AuditTable";

const PAGE_SIZE = 50;

export default function PlatformAuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [organizations, setOrganizations] = useState<OrganizationHealth[]>([]);
  const [organizationId, setOrganizationId] = useState("");
  const [actorEmail, setActorEmail] = useState("");
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (organizationId) params.set("organization_id", organizationId);
      if (actorEmail.trim()) params.set("actor_email", actorEmail.trim());

      const page = await api.get<Page<AuditEntry>>(`/platform/audit-log?${params}`);
      setEntries(page.items);
      setTotal(page.total);
      setError(null);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "We could not load the audit log.",
      );
    } finally {
      setLoading(false);
    }
  }, [organizationId, actorEmail, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api
      .get<OrganizationHealth[]>("/platform-admin/organizations")
      .then(setOrganizations)
      .catch(() => setOrganizations([]));
  }, []);

  const to = Math.min(offset + PAGE_SIZE, total);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-ink-900">
          {strings.audit.platformTitle}
        </h1>
        <p className="mt-1 text-sm text-ink-500">{strings.audit.platformSubtitle}</p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1.5">
          <span className="block text-xs font-medium uppercase tracking-wider text-ink-400">
            {strings.audit.filterOrg}
          </span>
          <select
            value={organizationId}
            onChange={(event) => {
              setOffset(0);
              setOrganizationId(event.target.value);
            }}
            className="light-input"
          >
            <option value="">{strings.audit.allOrgs}</option>
            {organizations.map(({ organization }) => (
              <option key={organization.id} value={organization.id}>
                {organization.name}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1.5">
          <span className="block text-xs font-medium uppercase tracking-wider text-ink-400">
            {strings.audit.filterActor}
          </span>
          <input
            value={actorEmail}
            onChange={(event) => {
              setOffset(0);
              setActorEmail(event.target.value);
            }}
            placeholder="name@company.com"
            className="light-input"
          />
        </label>
        {(organizationId || actorEmail) && (
          <button
            onClick={() => {
              setOrganizationId("");
              setActorEmail("");
              setOffset(0);
            }}
            className="fb-button-ghost !border-ink-200 !text-ink-600 hover:!bg-ink-100"
          >
            {strings.audit.clear}
          </button>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      <section className="overflow-hidden rounded-xl border border-ink-200 bg-white">
        <AuditTable
          entries={entries}
          loading={loading}
          showOrganization
          variant="light"
        />
      </section>

      <div className="flex items-center justify-between text-xs text-ink-500">
        <span className="fb-numeric">
          {strings.audit.showing} {total === 0 ? 0 : offset + 1}–{to} of {total}
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
            className="fb-button-ghost !border-ink-200 !py-1 !text-ink-600 hover:!bg-ink-100 disabled:opacity-40"
          >
            {strings.audit.newer}
          </button>
          <button
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={to >= total}
            className="fb-button-ghost !border-ink-200 !py-1 !text-ink-600 hover:!bg-ink-100 disabled:opacity-40"
          >
            {strings.audit.older}
          </button>
        </div>
      </div>
    </div>
  );
}
