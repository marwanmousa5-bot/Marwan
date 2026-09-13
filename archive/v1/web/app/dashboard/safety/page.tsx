"use client";

/**
 * Driver safety scores, points and the monthly leaderboard (Sections 4g, 5.1).
 *
 * Every number here is explainable: the score shows the distance it was
 * computed over, the fatigue level shows its reasons, and a driver's points
 * balance links to the ledger entry that produced it.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import type { DriverScore, Leaderboard, PointsLedgerEntry } from "@/lib/types";
import { Meter } from "@/components/charts/Meter";
import { STATUS, formatNumber } from "@/components/charts/tokens";

const FATIGUE_STYLES: Record<string, { label: string; className: string }> = {
  low: { label: "Low", className: "bg-success/10 text-success" },
  moderate: { label: "Moderate", className: "bg-warning/10 text-warning" },
  high: { label: "High", className: "bg-danger/10 text-danger" },
};

export default function SafetyPage() {
  const { session } = useSession();
  const isAdmin = session?.user.role === "org_admin";

  const [scores, setScores] = useState<DriverScore[]>([]);
  const [board, setBoard] = useState<Leaderboard | null>(null);
  const [ledger, setLedger] = useState<PointsLedgerEntry[] | null>(null);
  const [ledgerFor, setLedgerFor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [scoreRows, leaderboard] = await Promise.all([
        api.get<DriverScore[]>("/analytics/driver-scores"),
        api.get<Leaderboard>("/leaderboard"),
      ]);
      setScores(scoreRows);
      setBoard(leaderboard);
      setError(null);
    } catch {
      setError("We could not load driver safety data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function recompute() {
    setBusy(true);
    try {
      await api.post("/analytics/recompute");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  }

  async function openLedger(driverId: string, name: string) {
    setLedgerFor(name);
    try {
      setLedger(await api.get<PointsLedgerEntry[]>(`/drivers/${driverId}/points`));
    } catch {
      setLedger([]);
    }
  }

  const badgeNames = new Map(
    (board?.badge_catalogue ?? []).map((badge) => [badge.code, badge.name]),
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white">{strings.safety.title}</h1>
          <p className="mt-1 text-sm text-ink-300">{strings.safety.subtitle}</p>
        </div>
        {isAdmin && (
          <button onClick={recompute} disabled={busy} className="fb-button-ghost">
            {busy ? "Recomputing…" : strings.safety.recompute}
          </button>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <section className="fb-card">
          <h2 className="border-b border-ink-600/70 px-4 py-3 text-sm font-semibold text-white">
            {strings.safety.scores}
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <thead className="border-b border-ink-600/70 text-xs uppercase tracking-wide text-ink-400">
                <tr>
                  <th scope="col" className="px-4 py-2.5 font-medium">Driver</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Safety score</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">
                    {strings.safety.fatigue}
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    Distance
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    {strings.safety.points}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-600/50">
                {loading ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-xs text-ink-400">
                      {strings.common.loading}
                    </td>
                  </tr>
                ) : scores.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-xs text-ink-400">
                      No drivers yet.
                    </td>
                  </tr>
                ) : (
                  scores.map((score) => {
                    const fatigue =
                      FATIGUE_STYLES[score.fatigue_risk_level] ?? FATIGUE_STYLES.low;
                    const violationCount = Object.values(score.violations).reduce(
                      (sum, count) => sum + count,
                      0,
                    );
                    return (
                      <tr key={score.driver_id} className="hover:bg-ink-700/40">
                        <td className="px-4 py-3">
                          <span className="text-ink-50">{score.driver_name}</span>
                          {violationCount > 0 && (
                            <span className="block text-[11px] text-ink-400">
                              {violationCount} violation
                              {violationCount === 1 ? "" : "s"} in 30 days
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <Meter
                            value={score.safety_score}
                            band={score.score_band}
                            provisional={score.provisional}
                          />
                        </td>
                        <td className="px-4 py-3">
                          {/* Status ships with a written label, never colour alone. */}
                          <span className={`fb-badge ${fatigue.className}`}>
                            {fatigue.label}
                          </span>
                          {score.fatigue_reasons.length > 0 && (
                            <span className="block text-[11px] text-ink-400">
                              {score.fatigue_reasons[0]}
                            </span>
                          )}
                        </td>
                        <td className="fb-numeric px-4 py-3 text-right text-ink-300">
                          {formatNumber(score.distance_km, 0)} km
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            onClick={() =>
                              openLedger(score.driver_id, score.driver_name)
                            }
                            className="fb-numeric text-xs text-electric-300 hover:text-electric-200"
                          >
                            {score.points_balance}
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="fb-card">
          <div className="border-b border-ink-600/70 px-4 py-3">
            <h2 className="text-sm font-semibold text-white">
              {strings.safety.leaderboard}
              {board && (
                <span className="ml-2 text-xs font-normal text-ink-400">
                  {board.period}
                </span>
              )}
            </h2>
            <p className="mt-1 text-[11px] leading-relaxed text-ink-400">
              {board?.visible_to_drivers
                ? strings.safety.leaderboardShownNote
                : strings.safety.leaderboardHiddenNote}
            </p>
          </div>

          <ol className="divide-y divide-ink-600/50">
            {(board?.rows ?? []).map((row) => (
              <li
                key={row.driver_id}
                className="flex items-center gap-3 px-4 py-2.5"
              >
                <span
                  className="fb-numeric w-6 shrink-0 text-center text-xs font-semibold"
                  style={{ color: row.rank <= 3 ? STATUS.good : undefined }}
                >
                  {row.rank}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs text-ink-50">
                    {row.driver_name}
                  </span>
                  {row.badges.length > 0 && (
                    <span className="mt-0.5 flex flex-wrap gap-1">
                      {row.badges.map((code) => (
                        <span
                          key={code}
                          className="fb-badge bg-electric/10 text-electric-300"
                          title={badgeNames.get(code) ?? code}
                        >
                          {badgeNames.get(code) ?? code}
                        </span>
                      ))}
                    </span>
                  )}
                </span>
                <span className="fb-numeric shrink-0 text-sm font-semibold text-white">
                  {row.points_balance}
                </span>
              </li>
            ))}
            {(board?.rows.length ?? 0) === 0 && !loading && (
              <li className="px-4 py-5 text-xs text-ink-400">
                No drivers on the board yet.
              </li>
            )}
          </ol>
        </section>
      </div>

      {ledger && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/70 p-4">
          <div className="fb-card w-full max-w-lg">
            <div className="flex items-center justify-between border-b border-ink-600/70 px-5 py-3">
              <h2 className="text-sm font-semibold text-white">
                Points history — {ledgerFor}
              </h2>
              <button
                onClick={() => setLedger(null)}
                aria-label="Close"
                className="rounded p-1 text-ink-400 hover:bg-ink-700 hover:text-white"
              >
                ×
              </button>
            </div>
            <ul className="max-h-96 divide-y divide-ink-600/50 overflow-y-auto">
              {ledger.length === 0 ? (
                <li className="px-5 py-5 text-xs text-ink-400">
                  Nothing has changed this driver&apos;s balance yet.
                </li>
              ) : (
                ledger.map((entry) => (
                  <li
                    key={entry.id}
                    className="flex items-baseline justify-between gap-3 px-5 py-2.5"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-xs text-ink-100">
                        {entry.reason}
                      </span>
                      <span className="text-[10px] text-ink-500">
                        {new Date(entry.created_at).toLocaleString()}
                      </span>
                    </span>
                    <span
                      className={`fb-numeric shrink-0 text-xs font-semibold ${
                        entry.delta < 0 ? "text-danger" : "text-success"
                      }`}
                    >
                      {entry.delta > 0 ? "+" : ""}
                      {entry.delta}
                      <span className="ml-2 font-normal text-ink-400">
                        → {entry.balance_after}
                      </span>
                    </span>
                  </li>
                ))
              )}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
