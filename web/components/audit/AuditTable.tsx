"use client";

/**
 * The audit trail table, shared by the organisation and platform views
 * (Section 4 item 18).
 *
 * A row is only useful if you can see what actually changed, so each entry
 * with a diff expands into a before/after list rather than dumping JSON.
 */

import { useState } from "react";

import { strings } from "@/lib/strings";
import type { AuditEntry } from "@/lib/types";

/** Verbs that describe a security event rather than a data change. */
const SECURITY_ACTIONS = new Set([
  "login_failure",
  "suspicious_login_flagged",
  "impersonation_started",
  "organization_suspended",
]);

export function actionLabel(action: string): string {
  return action.replace(/_/g, " ");
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * The stored shape is one before/after pair of field maps, and a creation
 * carries only "after". Flatten it to per-field rows for display.
 */
function changedFields(
  changes: AuditEntry["changes"],
): { field: string; before: unknown; after: unknown }[] {
  if (!changes) return [];
  const before = (changes.before ?? {}) as Record<string, unknown>;
  const after = (changes.after ?? {}) as Record<string, unknown>;
  const fields = [...new Set([...Object.keys(after), ...Object.keys(before)])];
  return fields.map((field) => ({
    field,
    before: before[field],
    after: after[field],
  }));
}

/**
 * The console is dark and the Platform Admin Console is deliberately light
 * (Section 4a), so the one table has to read correctly on both grounds.
 */
const THEMES = {
  dark: {
    head: "border-b border-ink-600/70 text-xs uppercase tracking-wide text-ink-400",
    body: "divide-y divide-ink-600/50",
    row: "align-top hover:bg-ink-700/40",
    muted: "text-ink-300",
    strong: "text-ink-100",
    faint: "text-ink-500",
    neutralBadge: "bg-ink-700 text-ink-200",
    diff: "mt-2 space-y-1 rounded border border-ink-600 p-2",
  },
  light: {
    head: "border-b border-ink-200 text-xs uppercase tracking-wide text-ink-400",
    body: "divide-y divide-ink-100",
    row: "align-top hover:bg-ink-50",
    muted: "text-ink-500",
    strong: "text-ink-900",
    faint: "text-ink-400",
    neutralBadge: "bg-ink-100 text-ink-600",
    diff: "mt-2 space-y-1 rounded border border-ink-200 p-2",
  },
} as const;

export function AuditTable({
  entries,
  loading,
  showOrganization = false,
  variant = "dark",
}: {
  entries: AuditEntry[];
  loading?: boolean;
  showOrganization?: boolean;
  variant?: keyof typeof THEMES;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const theme = THEMES[variant];

  if (loading) {
    return <p className={`px-4 py-6 text-sm ${theme.muted}`}>{strings.common.loading}</p>;
  }
  if (entries.length === 0) {
    return <p className={`px-4 py-6 text-sm ${theme.muted}`}>{strings.audit.empty}</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm" style={{ minWidth: "52rem" }}>
        <thead className={theme.head}>
          <tr>
            <th scope="col" className="px-4 py-2.5 font-medium">
              {strings.audit.when}
            </th>
            <th scope="col" className="px-4 py-2.5 font-medium">
              {strings.audit.who}
            </th>
            {showOrganization && (
              <th scope="col" className="px-4 py-2.5 font-medium">
                {strings.audit.organization}
              </th>
            )}
            <th scope="col" className="px-4 py-2.5 font-medium">
              {strings.audit.action}
            </th>
            <th scope="col" className="px-4 py-2.5 font-medium">
              {strings.audit.what}
            </th>
          </tr>
        </thead>
        <tbody className={theme.body}>
          {entries.map((entry) => {
            const changes = changedFields(entry.changes);
            const open = expanded === entry.id;
            return (
              <tr key={entry.id} className={theme.row}>
                <td
                  className={`fb-numeric whitespace-nowrap px-4 py-2.5 text-xs ${theme.muted}`}
                >
                  {new Date(entry.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-2.5">
                  <span className={`block text-xs ${theme.strong}`}>
                    {entry.actor_email ?? strings.audit.system}
                  </span>
                  {entry.actor_role && (
                    <span className={`block text-[11px] ${theme.faint}`}>
                      {entry.actor_role.replace(/_/g, " ")}
                    </span>
                  )}
                  {entry.impersonator_user_id && (
                    <span className="fb-badge mt-1 inline-block bg-coral/15 text-coral">
                      {strings.audit.impersonated}
                    </span>
                  )}
                </td>
                {showOrganization && (
                  <td className={`px-4 py-2.5 text-xs ${theme.strong}`}>
                    {entry.organization_name ?? strings.audit.platformLevel}
                  </td>
                )}
                <td className="px-4 py-2.5">
                  <span
                    className={`fb-badge ${
                      SECURITY_ACTIONS.has(entry.action)
                        ? "bg-coral/15 text-coral"
                        : theme.neutralBadge
                    }`}
                  >
                    {actionLabel(entry.action)}
                  </span>
                </td>
                <td className="px-4 py-2.5">
                  <span className={`block text-xs ${theme.strong}`}>
                    {entry.summary ?? "—"}
                  </span>
                  {entry.ip_address && (
                    <span className={`block text-[11px] ${theme.faint}`}>
                      {entry.ip_address}
                    </span>
                  )}
                  {changes.length > 0 && (
                    <>
                      <button
                        onClick={() => setExpanded(open ? null : entry.id)}
                        aria-expanded={open}
                        className="mt-1 text-[11px] text-electric-300 hover:text-electric-200"
                      >
                        {open ? strings.audit.hideChanges : strings.audit.showChanges}
                      </button>
                      {open && (
                        <dl className={theme.diff}>
                          {changes.map(({ field, before, after }) => (
                            <div key={field} className="text-[11px]">
                              <dt className={theme.muted}>
                                {field.replace(/_/g, " ")}
                              </dt>
                              <dd className={theme.strong}>
                                {before === undefined ? (
                                  // A creation has no "before" - saying
                                  // "— → value" would imply it was cleared.
                                  <span>{formatValue(after)}</span>
                                ) : (
                                  <>
                                    <span className={`${theme.faint} line-through`}>
                                      {formatValue(before)}
                                    </span>
                                    {" → "}
                                    <span>{formatValue(after)}</span>
                                  </>
                                )}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      )}
                    </>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
