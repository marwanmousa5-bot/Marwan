"use client";

/**
 * Fleet Copilot panel (Section 4e) - lives in the Live Tracking right rail.
 *
 * Cards are read-only until a person acts on them. "Apply" opens a second
 * confirmation step inside the card rather than calling straight through,
 * because applying can reassign a task or open a work order (Section 9).
 * Informational cards have no Apply button at all.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import type { Recommendation } from "@/lib/types";

const KIND_LABEL: Record<Recommendation["kind"], string> = {
  copilot: "Operations",
  maintenance_window: "Maintenance",
  reroute: "Routing",
  ev_transition: "Sustainability",
  anomaly: "Anomaly",
};

export function CopilotPanel({
  onFocusVehicle,
}: {
  onFocusVehicle?: (vehicleId: string) => void;
}) {
  const { session } = useSession();
  const [items, setItems] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canApply = session?.user.role === "org_admin";

  const load = useCallback(async () => {
    try {
      setItems(await api.get<Recommendation[]>("/copilot/recommendations"));
      setError(null);
    } catch {
      setError(strings.copilot.failed);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function reanalyse() {
    setRunning(true);
    setError(null);
    try {
      setItems(await api.post<Recommendation[]>("/copilot/run"));
    } catch {
      setError(strings.copilot.failed);
    } finally {
      setRunning(false);
    }
  }

  async function apply(item: Recommendation) {
    setBusyId(item.id);
    setError(null);
    try {
      const updated = await api.post<Recommendation>(
        `/copilot/recommendations/${item.id}/apply`,
      );
      setItems((current) => current.filter((r) => r.id !== updated.id));
      setConfirming(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : strings.copilot.failed);
    } finally {
      setBusyId(null);
    }
  }

  async function dismiss(item: Recommendation) {
    setBusyId(item.id);
    try {
      await api.post<Recommendation>(
        `/copilot/recommendations/${item.id}/dismiss`,
      );
      setItems((current) => current.filter((r) => r.id !== item.id));
    } catch {
      setError(strings.copilot.failed);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b border-ink-700 px-3 py-2">
        <p className="text-[11px] leading-relaxed text-ink-400">
          {strings.copilot.subtitle}
        </p>
        <button
          onClick={reanalyse}
          disabled={running}
          className="fb-button-ghost shrink-0 !py-1 text-[11px] disabled:opacity-50"
        >
          {running ? strings.copilot.running : strings.copilot.run}
        </button>
      </div>

      <ul className="min-h-0 flex-1 divide-y divide-ink-700/60 overflow-y-auto">
        {loading ? (
          <li className="px-3 py-4 text-xs text-ink-400">{strings.common.loading}</li>
        ) : items.length === 0 ? (
          <li className="px-3 py-4 text-xs text-ink-400">{strings.copilot.empty}</li>
        ) : (
          items.map((item) => {
            const actionable = Boolean(item.action_payload?.op);
            return (
              <li key={item.id} className="px-3 py-3">
                <div className="flex items-center gap-2">
                  <span className="fb-badge bg-electric/15 text-electric-300">
                    {KIND_LABEL[item.kind] ?? item.kind}
                  </span>
                  {/* Ranks are stored 0-based; people count from one. */}
                  <span className="fb-numeric text-[10px] text-ink-500">
                    #{item.rank + 1}
                  </span>
                </div>

                <p className="mt-1.5 text-xs font-medium text-ink-50">{item.title}</p>
                <p className="mt-1 text-[11px] leading-relaxed text-ink-400">
                  {item.summary}
                </p>

                {item.estimated_benefit && (
                  <p className="mt-1.5 text-[11px] text-success">
                    {strings.copilot.benefit}: {item.estimated_benefit}
                  </p>
                )}

                {confirming === item.id ? (
                  <div className="mt-2.5 rounded-lg border border-warning/40 bg-warning/5 p-2.5">
                    <p className="text-[11px] font-semibold text-warning">
                      {strings.copilot.confirmApply}
                    </p>
                    <p className="mt-1 text-[11px] leading-relaxed text-ink-300">
                      {item.suggested_action ?? strings.copilot.confirmApplyHint}
                    </p>
                    <div className="mt-2.5 flex gap-2">
                      <button
                        onClick={() => apply(item)}
                        disabled={busyId === item.id}
                        className="fb-button-primary !py-1 text-[11px] disabled:opacity-50"
                      >
                        {strings.copilot.apply}
                      </button>
                      <button
                        onClick={() => setConfirming(null)}
                        className="fb-button-ghost !py-1 text-[11px]"
                      >
                        {strings.common.cancel}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="mt-2.5 flex flex-wrap items-center gap-3">
                    {actionable &&
                      (canApply ? (
                        <button
                          onClick={() => setConfirming(item.id)}
                          className="text-[11px] text-electric-300 hover:text-electric-200"
                        >
                          {strings.copilot.apply}
                        </button>
                      ) : (
                        <span className="text-[10px] text-ink-500">
                          {strings.copilot.adminOnly}
                        </span>
                      ))}
                    {!actionable && (
                      <span className="text-[10px] text-ink-500">
                        {strings.copilot.informational}
                      </span>
                    )}
                    {item.vehicle_id && onFocusVehicle && (
                      <button
                        onClick={() => onFocusVehicle(item.vehicle_id as string)}
                        className="text-[10px] text-ink-400 hover:text-ink-200"
                      >
                        Show on map
                      </button>
                    )}
                    <button
                      onClick={() => dismiss(item)}
                      disabled={busyId === item.id}
                      className="text-[10px] text-ink-400 hover:text-ink-200 disabled:opacity-50"
                    >
                      {strings.copilot.dismiss}
                    </button>
                  </div>
                )}
              </li>
            );
          })
        )}
      </ul>

      {error && (
        <p role="alert" className="bg-danger/10 px-3 py-2 text-[11px] text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
