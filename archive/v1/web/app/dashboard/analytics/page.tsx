"use client";

/**
 * Analytics, cost/TCO and sustainability (Sections 4.10, 4.13, 4.15, 4.17).
 *
 * Headline numbers are stat tiles, not charts. Trends are small multiples -
 * one measure per plot - because distance, cost, CO2 and violations live on
 * different scales and a second y-axis is the easiest way to make a dashboard
 * lie. Cost composition is the only place a categorical palette appears.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import { strings } from "@/lib/strings";
import type {
  AnalyticsAnomaly,
  AssetSummary,
  EvCandidate,
  FleetKpis,
  MaintenanceForecast,
  TrendPoint,
} from "@/lib/types";
import { CostBreakdown, type CostRow } from "@/components/charts/CostBreakdown";
import { StatTile } from "@/components/charts/StatTile";
import { TrendChart } from "@/components/charts/TrendChart";
import { formatNumber } from "@/components/charts/tokens";

const RANGES = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
] as const;

function isoDaysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

function monthLabel(period: string): string {
  const [year, month] = period.split("-").map(Number);
  return new Date(year, month - 1, 1).toLocaleDateString(undefined, {
    month: "short",
  });
}

export default function AnalyticsPage() {
  const [days, setDays] = useState<number>(30);
  const [kpis, setKpis] = useState<FleetKpis | null>(null);
  const [costs, setCosts] = useState<CostRow[]>([]);
  const [trends, setTrends] = useState<TrendPoint[]>([]);
  const [evCandidates, setEvCandidates] = useState<EvCandidate[]>([]);
  const [assets, setAssets] = useState<AssetSummary[]>([]);
  const [anomalies, setAnomalies] = useState<AnalyticsAnomaly[]>([]);
  const [forecast, setForecast] = useState<MaintenanceForecast[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (windowDays: number) => {
    setLoading(true);
    try {
      const range = `date_from=${isoDaysAgo(windowDays)}`;
      const [kpiData, costData, trendData, ev, assetData, anomalyData, forecastData] =
        await Promise.all([
          api.get<FleetKpis>(`/analytics/kpis?${range}`),
          api.get<CostRow[]>(`/analytics/costs?${range}`),
          api.get<TrendPoint[]>("/analytics/trends?months=6"),
          api.get<EvCandidate[]>("/analytics/ev-candidates"),
          api.get<AssetSummary[]>("/analytics/assets"),
          api.get<AnalyticsAnomaly[]>("/analytics/anomalies"),
          api.get<MaintenanceForecast[]>("/analytics/maintenance-forecast"),
        ]);
      setKpis(kpiData);
      setCosts(costData);
      setTrends(trendData);
      setEvCandidates(ev);
      setAssets(assetData);
      setAnomalies(anomalyData);
      setForecast(forecastData);
      setError(null);
    } catch {
      setError("We could not load your analytics.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(days);
  }, [days, load]);

  const series = useMemo(
    () => ({
      distance: trends.map((t) => ({ label: monthLabel(t.period), value: t.distance_km })),
      cost: trends.map((t) => ({ label: monthLabel(t.period), value: t.cost })),
      co2: trends.map((t) => ({ label: monthLabel(t.period), value: t.co2_kg })),
      violations: trends.map((t) => ({
        label: monthLabel(t.period),
        value: t.violations,
      })),
    }),
    [trends],
  );

  const replacements = assets.filter((a) => a.replacement_recommended);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white">
            {strings.analytics.title}
          </h1>
          <p className="mt-1 text-sm text-ink-300">{strings.analytics.subtitle}</p>
        </div>
        {/* Filters sit in one row above the charts. */}
        <div className="flex rounded-md border border-ink-600">
          {RANGES.map((range) => (
            <button
              key={range.days}
              onClick={() => setDays(range.days)}
              aria-pressed={days === range.days}
              className={`px-3 py-1.5 text-xs transition ${
                days === range.days
                  ? "bg-ink-600 text-white"
                  : "text-ink-300 hover:text-white"
              }`}
            >
              {range.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
        <StatTile
          label="Total cost"
          value={loading || !kpis ? "—" : formatNumber(kpis.total_cost, 2)}
        />
        <StatTile
          label="Cost per km"
          value={
            loading || !kpis || kpis.cost_per_km == null
              ? "—"
              : formatNumber(kpis.cost_per_km, 3)
          }
        />
        <StatTile
          label="Distance"
          value={loading || !kpis ? "—" : formatNumber(kpis.distance_km, 0)}
          unit="km"
        />
        <StatTile
          label="Utilisation"
          value={loading || !kpis ? "—" : formatNumber(kpis.utilisation_percent, 0)}
          unit="%"
          hint="Active vehicles that moved"
        />
        <StatTile
          label="CO₂"
          value={loading || !kpis ? "—" : formatNumber(kpis.co2_kg, 0)}
          unit="kg"
        />
        <StatTile
          label="Avg safety score"
          value={
            loading || !kpis ? "—" : formatNumber(kpis.average_safety_score, 0)
          }
          tone={
            !kpis
              ? "neutral"
              : kpis.average_safety_score >= 85
                ? "good"
                : kpis.average_safety_score >= 70
                  ? "warning"
                  : "critical"
          }
        />
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-white">
          {strings.analytics.trends}
          <span className="ml-2 text-xs font-normal text-ink-400">
            last 6 months
          </span>
        </h2>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <TrendChart
            title={strings.analytics.distance}
            data={series.distance}
            unit="km"
          />
          {/*
            One hue across all four: these are independent measures on their
            own axes, not a series set. Colouring them differently would imply
            a categorical encoding that does not exist.
          */}
          <TrendChart title={strings.analytics.cost} data={series.cost} digits={2} />
          <TrendChart
            title={strings.analytics.emissions}
            data={series.co2}
            unit="kg"
          />
          <TrendChart title={strings.analytics.violations} data={series.violations} />
        </div>
      </section>

      <CostBreakdown rows={costs} />

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="fb-card">
          <h2 className="border-b border-ink-600/70 px-4 py-3 text-sm font-semibold text-white">
            {strings.analytics.evTitle}
          </h2>
          {evCandidates.length === 0 ? (
            <p className="px-4 py-5 text-xs leading-relaxed text-ink-400">
              {strings.analytics.evEmpty}
            </p>
          ) : (
            <ul className="divide-y divide-ink-600/50">
              {evCandidates.map((candidate) => (
                <li key={candidate.vehicle_id} className="px-4 py-3">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-xs font-medium text-ink-50">
                      {candidate.vehicle_name}
                      <span className="ml-2 text-ink-400">
                        {candidate.license_plate}
                      </span>
                    </span>
                    <span className="fb-numeric shrink-0 text-xs text-success">
                      ~{formatNumber(candidate.annual_fuel_cost, 0)}/yr fuel
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] leading-relaxed text-ink-400">
                    {candidate.rationale}
                  </p>
                  <p className="fb-numeric mt-1 text-[10px] text-ink-500">
                    avg {formatNumber(candidate.average_daily_km, 0)} km/day · busiest{" "}
                    {formatNumber(candidate.max_daily_km, 0)} km ·{" "}
                    {candidate.days_observed} days observed
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="fb-card">
          <h2 className="border-b border-ink-600/70 px-4 py-3 text-sm font-semibold text-white">
            {strings.analytics.anomaliesTitle}
          </h2>
          {anomalies.length === 0 ? (
            <p className="px-4 py-5 text-xs text-ink-400">
              {strings.analytics.anomaliesEmpty}
            </p>
          ) : (
            <ul className="divide-y divide-ink-600/50">
              {anomalies.map((anomaly, index) => (
                <li key={`${anomaly.kind}-${index}`} className="px-4 py-3">
                  <p className="text-xs font-medium text-ink-50">
                    {anomaly.vehicle_name}
                    <span className="ml-2 text-ink-400">
                      {anomaly.kind.replace("_", " ")}
                    </span>
                  </p>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-ink-400">
                    {anomaly.summary}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="fb-card">
          <h2 className="border-b border-ink-600/70 px-4 py-3 text-sm font-semibold text-white">
            {strings.analytics.forecastTitle}
          </h2>
          {forecast.length === 0 ? (
            <p className="px-4 py-5 text-xs text-ink-400">
              {strings.analytics.forecastEmpty}
            </p>
          ) : (
            <ul className="divide-y divide-ink-600/50">
              {forecast.map((item) => (
                <li key={item.schedule_id} className="px-4 py-3">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-xs font-medium text-ink-50">
                      {item.schedule_name} · {item.vehicle_name}
                    </span>
                    <span
                      className={`fb-numeric shrink-0 text-xs ${
                        item.days_away <= 7 ? "text-warning" : "text-ink-300"
                      }`}
                    >
                      {item.days_away}d
                    </span>
                  </div>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-ink-400">
                    {item.summary}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="fb-card">
          <h2 className="border-b border-ink-600/70 px-4 py-3 text-sm font-semibold text-white">
            {strings.analytics.assetsTitle}
            {replacements.length > 0 && (
              <span className="fb-badge ml-2 bg-warning/10 text-warning">
                {replacements.length} flagged
              </span>
            )}
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[32rem] text-left text-sm">
              <thead className="border-b border-ink-600/70 text-xs uppercase tracking-wide text-ink-400">
                <tr>
                  <th scope="col" className="px-4 py-2.5 font-medium">Vehicle</th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">Age</th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    Book value
                  </th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-600/50">
                {assets.map((asset) => (
                  <tr key={asset.vehicle_id}>
                    <td className="px-4 py-2.5 text-ink-100">{asset.vehicle_name}</td>
                    <td className="fb-numeric px-4 py-2.5 text-right text-ink-300">
                      {asset.age_years != null ? `${asset.age_years.toFixed(1)}y` : "—"}
                    </td>
                    <td className="fb-numeric px-4 py-2.5 text-right text-ink-300">
                      {asset.book_value != null
                        ? formatNumber(asset.book_value, 0)
                        : "—"}
                    </td>
                    <td className="px-4 py-2.5">
                      {asset.replacement_recommended ? (
                        <span
                          className="fb-badge bg-warning/10 text-warning"
                          title={asset.reasons.join("; ")}
                        >
                          Replace
                        </span>
                      ) : (
                        <span className="text-xs text-ink-400">In service</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
