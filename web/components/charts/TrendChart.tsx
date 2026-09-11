"use client";

/**
 * Single-series trend over time, drawn as inline SVG.
 *
 * One measure per chart on purpose. Distance, cost, CO2 and violations live on
 * wildly different scales, and putting two of them on one plot would mean a
 * second y-axis - the single most misread thing in dashboards. Small multiples
 * say the same thing without the ambiguity.
 *
 * A single series needs no legend: the title already names what is plotted.
 */

import { useMemo, useState } from "react";

import { GRID, SERIES_PRIMARY, TEXT, formatNumber, niceMax } from "./tokens";

export interface TrendDatum {
  label: string;
  value: number;
}

const WIDTH = 320;
const HEIGHT = 120;
const PADDING = { top: 12, right: 14, bottom: 20, left: 40 };

export function TrendChart({
  title,
  data,
  unit,
  digits = 0,
  color = SERIES_PRIMARY,
}: {
  title: string;
  data: TrendDatum[];
  unit?: string;
  digits?: number;
  color?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);

  const { points, max, plotWidth, plotHeight } = useMemo(() => {
    const plotW = WIDTH - PADDING.left - PADDING.right;
    const plotH = HEIGHT - PADDING.top - PADDING.bottom;
    const maxValue = niceMax(Math.max(1, ...data.map((d) => d.value)));
    const step = data.length > 1 ? plotW / (data.length - 1) : 0;

    return {
      max: maxValue,
      plotWidth: plotW,
      plotHeight: plotH,
      points: data.map((datum, index) => ({
        ...datum,
        x: PADDING.left + index * step,
        y: PADDING.top + plotH - (datum.value / maxValue) * plotH,
      })),
    };
  }, [data]);

  if (data.length === 0) {
    return (
      <figure className="fb-card p-4">
        <figcaption className="fb-label mb-2">{title}</figcaption>
        <p className="py-6 text-center text-xs" style={{ color: TEXT.muted }}>
          No data for this period.
        </p>
      </figure>
    );
  }

  const line = points.map((p) => `${p.x},${p.y}`).join(" ");
  const areaPath =
    `M ${points[0].x},${PADDING.top + plotHeight} ` +
    points.map((p) => `L ${p.x},${p.y}`).join(" ") +
    ` L ${points[points.length - 1].x},${PADDING.top + plotHeight} Z`;

  const last = points[points.length - 1];
  const active = hover !== null ? points[hover] : null;

  return (
    <figure className="fb-card p-4">
      <figcaption className="flex items-baseline justify-between gap-2">
        <span className="fb-label">{title}</span>
        {/*
          The headline is the latest point, not a period total - so it carries
          its own period label. Without it, a part-way-through month reads as
          "we spent nothing", flatly contradicting the line underneath.
        */}
        <span className="flex items-baseline gap-1.5">
          <span className="text-[10px]" style={{ color: TEXT.muted }}>
            {last.label}
          </span>
          <span className="fb-numeric text-sm font-semibold text-white">
            {formatNumber(last.value, digits)}
            {unit && (
              <span
                className="ml-1 text-[11px] font-normal"
                style={{ color: TEXT.muted }}
              >
                {unit}
              </span>
            )}
          </span>
        </span>
      </figcaption>

      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="mt-2 w-full"
        role="img"
        aria-label={`${title}: ${data
          .map((d) => `${d.label} ${formatNumber(d.value, digits)}`)
          .join(", ")}`}
        onMouseLeave={() => setHover(null)}
      >
        {/* Recessive hairline grid - solid, one step off the surface. */}
        {[0, 0.5, 1].map((fraction) => {
          const y = PADDING.top + plotHeight * fraction;
          return (
            <g key={fraction}>
              <line
                x1={PADDING.left}
                x2={WIDTH - PADDING.right}
                y1={y}
                y2={y}
                stroke={GRID}
                strokeWidth={1}
              />
              <text
                x={PADDING.left - 6}
                y={y + 3}
                textAnchor="end"
                fontSize={8}
                fill={TEXT.muted}
              >
                {formatNumber(max * (1 - fraction), 0)}
              </text>
            </g>
          );
        })}

        {/* Area wash at ~10% - never a saturated block. */}
        <path d={areaPath} fill={color} opacity={0.1} />
        <polyline
          points={line}
          fill="none"
          stroke={color}
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {active && (
          <line
            x1={active.x}
            x2={active.x}
            y1={PADDING.top}
            y2={PADDING.top + plotHeight}
            stroke={TEXT.muted}
            strokeWidth={1}
          />
        )}

        {/* End marker: >=8px with a 2px surface ring so it reads over the line. */}
        <circle
          cx={last.x}
          cy={last.y}
          r={4}
          fill={color}
          stroke="#181B20"
          strokeWidth={2}
        />
        {active && active !== last && (
          <circle
            cx={active.x}
            cy={active.y}
            r={4}
            fill={color}
            stroke="#181B20"
            strokeWidth={2}
          />
        )}

        {/* Hit targets are wider than the marks. */}
        {points.map((point, index) => (
          <rect
            key={point.label}
            x={point.x - plotWidth / Math.max(1, data.length * 2)}
            y={PADDING.top}
            width={Math.max(12, plotWidth / Math.max(1, data.length))}
            height={plotHeight}
            fill="transparent"
            onMouseEnter={() => setHover(index)}
          />
        ))}

        <text
          x={PADDING.left}
          y={HEIGHT - 6}
          fontSize={8}
          fill={TEXT.muted}
        >
          {data[0].label}
        </text>
        <text
          x={WIDTH - PADDING.right}
          y={HEIGHT - 6}
          fontSize={8}
          fill={TEXT.muted}
          textAnchor="end"
        >
          {data[data.length - 1].label}
        </text>
      </svg>

      <p
        className="fb-numeric mt-1 h-4 text-[11px]"
        style={{ color: TEXT.secondary }}
      >
        {active
          ? `${active.label}: ${formatNumber(active.value, digits)}${unit ? ` ${unit}` : ""}`
          : ""}
      </p>
    </figure>
  );
}
