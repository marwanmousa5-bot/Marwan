/**
 * Chart tokens for FleetBeat's dark control-room surface.
 *
 * The categorical slots were validated with the data-viz palette validator
 * against the chart surface (#181B20), not chosen by eye:
 *
 *   node validate_palette.js "#1E90FF,#199E70,#9085E9" --mode dark --surface "#181B20"
 *   Lightness band PASS · Chroma floor PASS
 *   CVD separation PASS (worst adjacent dE 17.3, deutan)
 *   Normal-vision floor PASS (worst adjacent dE 23.2)
 *   Contrast vs surface PASS (all >= 3:1)
 *
 * Alert Coral (#FF6B35) is deliberately absent: the brand reserves it for
 * live and critical indicators, and a series wearing it would compete with
 * the alert states everywhere else in the product. The status colours are
 * likewise reserved and never used as a series.
 */

export const CHART_SURFACE = "#181B20";

/** Categorical slots, assigned in fixed order and never cycled. */
export const SERIES = ["#1E90FF", "#199E70", "#9085E9"] as const;

/** Single-series (sequential) default: the brand hue. */
export const SERIES_PRIMARY = SERIES[0];

/** Text tokens - labels never wear the series colour. */
export const TEXT = {
  primary: "#E1E5EC",
  secondary: "#B9C0CC",
  muted: "#8A93A3",
} as const;

/** One step off the surface: grid and axes stay recessive. */
export const GRID = "#2A2F38";

/** Status palette, reserved and never reused as a series. */
export const STATUS = {
  good: "#2ECC71",
  warning: "#F5A623",
  critical: "#E74C3C",
} as const;

export function formatNumber(value: number, digits = 0): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Round an axis maximum up to a clean tick value. */
export function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalised = value / magnitude;
  const step = normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10;
  return step * magnitude;
}
