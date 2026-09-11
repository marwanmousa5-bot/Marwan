"use client";

/**
 * Cost composition per vehicle: a horizontal stacked bar.
 *
 * Horizontal because vehicle names are long, stacked because the job is
 * part-to-whole. Three categorical slots, assigned in fixed order - the same
 * colour always means the same cost type, whatever the filter leaves on
 * screen. Segments are separated by a 2px gap in the surface colour rather
 * than by a stroke, so no non-data ink is added.
 *
 * A table view is always available: it is how the exact figures are read, and
 * how the chart stays usable when colour alone is not enough.
 */

import { useMemo, useState } from "react";

import { CHART_SURFACE, SERIES, TEXT, formatNumber } from "./tokens";

export interface CostRow {
  vehicle_id: string;
  vehicle_name: string;
  license_plate: string;
  fuel_cost: number;
  maintenance_cost: number;
  compliance_cost: number;
  total_cost: number;
  distance_km: number;
  cost_per_km: number | null;
}

const SEGMENTS = [
  { key: "fuel_cost", label: "Fuel & energy", color: SERIES[0] },
  { key: "maintenance_cost", label: "Maintenance", color: SERIES[1] },
  { key: "compliance_cost", label: "Compliance", color: SERIES[2] },
] as const;

const BAR_HEIGHT = 18; // <= 24px: the band keeps its air
const GAP_PX = 2;

export function CostBreakdown({
  rows,
  currency = "",
}: {
  rows: CostRow[];
  currency?: string;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const [hover, setHover] = useState<{ row: string; segment: string } | null>(null);

  const withCosts = useMemo(
    () =>
      [...rows]
        .filter((row) => row.total_cost > 0)
        .sort((a, b) => b.total_cost - a.total_cost),
    [rows],
  );
  const max = Math.max(1, ...withCosts.map((r) => r.total_cost));

  if (withCosts.length === 0) {
    return (
      <section className="fb-card p-5">
        <h2 className="text-sm font-semibold text-white">Cost per vehicle</h2>
        <p className="mt-3 text-xs" style={{ color: TEXT.muted }}>
          No costs recorded for this period yet. Log a fill-up or complete a work
          order and it will appear here.
        </p>
      </section>
    );
  }

  return (
    <section className="fb-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-600/70 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-white">Cost per vehicle</h2>
          <p className="mt-0.5 text-[11px]" style={{ color: TEXT.muted }}>
            Fuel, maintenance and compliance over the selected period.
          </p>
        </div>
        <div className="flex items-center gap-4">
          {/* Legend is always present for two or more series. */}
          <ul className="flex flex-wrap gap-3">
            {SEGMENTS.map((segment) => (
              <li key={segment.key} className="flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className="h-2.5 w-2.5 rounded-sm"
                  style={{ backgroundColor: segment.color }}
                />
                <span className="text-[11px]" style={{ color: TEXT.secondary }}>
                  {segment.label}
                </span>
              </li>
            ))}
          </ul>
          <div className="flex rounded-md border border-ink-600">
            {(["chart", "table"] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setView(mode)}
                aria-pressed={view === mode}
                className={`px-2.5 py-1 text-[11px] capitalize transition ${
                  view === mode
                    ? "bg-ink-600 text-white"
                    : "text-ink-300 hover:text-white"
                }`}
              >
                {mode}
              </button>
            ))}
          </div>
        </div>
      </div>

      {view === "table" ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-left text-sm">
            <thead className="border-b border-ink-600/70 text-xs uppercase tracking-wide text-ink-400">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">Vehicle</th>
                {SEGMENTS.map((s) => (
                  <th key={s.key} scope="col" className="px-4 py-2.5 text-right font-medium">
                    {s.label}
                  </th>
                ))}
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Total</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Per km</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-600/50">
              {withCosts.map((row) => (
                <tr key={row.vehicle_id}>
                  <td className="px-4 py-2.5 text-ink-100">{row.vehicle_name}</td>
                  {SEGMENTS.map((s) => (
                    <td key={s.key} className="fb-numeric px-4 py-2.5 text-right text-ink-300">
                      {formatNumber(row[s.key], 2)}
                    </td>
                  ))}
                  <td className="fb-numeric px-4 py-2.5 text-right font-medium text-white">
                    {formatNumber(row.total_cost, 2)}
                  </td>
                  <td className="fb-numeric px-4 py-2.5 text-right text-ink-300">
                    {row.cost_per_km != null ? formatNumber(row.cost_per_km, 3) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <ul className="space-y-3 p-4">
          {withCosts.map((row) => (
            <li key={row.vehicle_id}>
              <div className="flex items-baseline justify-between gap-3">
                <span className="truncate text-xs text-ink-100">
                  {row.vehicle_name}
                  <span className="ml-2" style={{ color: TEXT.muted }}>
                    {row.license_plate}
                  </span>
                </span>
                {/* One direct label per bar, at the tip: the total. */}
                <span className="fb-numeric shrink-0 text-xs font-medium text-white">
                  {currency}
                  {formatNumber(row.total_cost, 2)}
                </span>
              </div>

              <div
                className="mt-1.5 flex overflow-hidden"
                style={{ height: BAR_HEIGHT, borderRadius: 4 }}
              >
                {SEGMENTS.map((segment, index) => {
                  const value = row[segment.key];
                  if (value <= 0) return null;
                  const widthPercent = (value / max) * 100;
                  const isHovered =
                    hover?.row === row.vehicle_id && hover.segment === segment.key;
                  return (
                    <div
                      key={segment.key}
                      onMouseEnter={() =>
                        setHover({ row: row.vehicle_id, segment: segment.key })
                      }
                      onMouseLeave={() => setHover(null)}
                      title={`${segment.label}: ${currency}${formatNumber(value, 2)}`}
                      style={{
                        width: `${widthPercent}%`,
                        backgroundColor: segment.color,
                        opacity: hover && !isHovered ? 0.55 : 1,
                        // The 2px separator is surface, not a stroke.
                        marginLeft: index === 0 ? 0 : GAP_PX,
                        borderTopLeftRadius: index === 0 ? 4 : 0,
                        borderBottomLeftRadius: index === 0 ? 4 : 0,
                      }}
                    />
                  );
                })}
              </div>

              <p
                className="fb-numeric mt-1 h-3.5 text-[10px]"
                style={{ color: TEXT.secondary }}
              >
                {hover?.row === row.vehicle_id
                  ? `${SEGMENTS.find((s) => s.key === hover.segment)?.label}: ${currency}${formatNumber(
                      row[hover.segment as (typeof SEGMENTS)[number]["key"]],
                      2,
                    )}`
                  : row.cost_per_km != null
                    ? `${currency}${formatNumber(row.cost_per_km, 3)} per km over ${formatNumber(row.distance_km, 0)} km`
                    : row.distance_km > 0
                      ? `Only ${formatNumber(row.distance_km, 0)} km recorded \u2014 too little to give a per-km figure`
                      : "No distance recorded for this period"}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
