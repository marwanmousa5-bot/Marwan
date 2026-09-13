"use client";

/**
 * Organisation audit trail (Section 4 item 18).
 *
 * Scoped server-side to the caller's own Organization - this page has no way
 * to ask for another tenant's entries, and an org_admin token cannot reach
 * the platform-wide endpoint at all.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import type { AuditEntry, Page } from "@/lib/types";
import { AuditTable, actionLabel } from "@/components/audit/AuditTable";
import { Pager } from "@/components/Pager";

const PAGE_SIZE = 50;

export default function AuditLogPage() {
  const { session } = useSession();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [actions, setActions] = useState<string[]>([]);
  const [action, setAction] = useState("");
  const [actorEmail, setActorEmail] = useState("");
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
      if (action) params.set("action", action);
      if (actorEmail.trim()) params.set("actor_email", actorEmail.trim());

      const page = await api.get<Page<AuditEntry>>(`/audit-log?${params}`);
      setEntries(page.items);
      setTotal(page.total);
      setError(null);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? "Only an organisation admin can read the audit log."
          : "We could not load the audit log.",
      );
    } finally {
      setLoading(false);
    }
  }, [action, actorEmail, offset]);

  useEffect(() => {
    if (!isAdmin) {
      setLoading(false);
      return;
    }
    void load();
  }, [load, isAdmin]);

  useEffect(() => {
    if (!isAdmin) return;
    api
      .get<string[]>("/audit-log/actions")
      .then(setActions)
      .catch(() => setActions([]));
  }, [isAdmin]);

  if (!isAdmin) {
    return (
      <p className="fb-card text-sm text-ink-300">
        Only an organisation admin can read the audit log.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-white">{strings.audit.title}</h1>
        <p className="mt-1 text-sm text-ink-300">{strings.audit.subtitle}</p>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-ink-300">
          <span className="fb-label">{strings.audit.filterAction}</span>
          <select
            value={action}
            onChange={(event) => {
              setOffset(0);
              setAction(event.target.value);
            }}
            className="fb-input mt-1 !py-1.5 text-xs"
          >
            <option value="">{strings.audit.allActions}</option>
            {actions.map((value) => (
              <option key={value} value={value}>
                {actionLabel(value)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-ink-300">
          <span className="fb-label">{strings.audit.filterActor}</span>
          <input
            value={actorEmail}
            onChange={(event) => {
              setOffset(0);
              setActorEmail(event.target.value);
            }}
            placeholder="name@company.com"
            className="fb-input mt-1 !py-1.5 text-xs"
          />
        </label>
        {(action || actorEmail) && (
          <button
            onClick={() => {
              setAction("");
              setActorEmail("");
              setOffset(0);
            }}
            className="fb-button-ghost !py-1.5 text-xs"
          >
            {strings.audit.clear}
          </button>
        )}
      </div>

      {error && (
        <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </p>
      )}

      <div className="fb-card !p-0">
        <AuditTable entries={entries} loading={loading} />
      </div>

      <Pager
        offset={offset}
        total={total}
        pageSize={PAGE_SIZE}
        onChange={setOffset}
      />
    </div>
  );
}
