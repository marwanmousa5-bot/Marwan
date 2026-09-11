import { STATUS, TEXT, formatNumber } from "./tokens";

/**
 * A single ratio against a limit - the right form for one score, where a
 * two-slice pie would be. The colour is a status, not a series: it ships
 * beside a written band label, so meaning never rests on colour alone.
 */
export function Meter({
  value,
  max = 100,
  band,
  provisional = false,
}: {
  value: number;
  max?: number;
  band?: string;
  provisional?: boolean;
}) {
  const ratio = Math.max(0, Math.min(1, value / max));
  const color =
    provisional
      ? TEXT.muted
      : ratio >= 0.9
        ? STATUS.good
        : ratio >= 0.75
          ? "#1E90FF"
          : ratio >= 0.6
            ? STATUS.warning
            : STATUS.critical;

  return (
    <span className="flex items-center gap-2">
      <span
        className="relative h-1.5 w-20 overflow-hidden rounded-full"
        style={{ backgroundColor: "#2A2F38" }}
        role="img"
        aria-label={`${formatNumber(value, 0)} out of ${max}${band ? `, ${band}` : ""}`}
      >
        <span
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${ratio * 100}%`, backgroundColor: color }}
        />
      </span>
      <span className="fb-numeric text-xs text-ink-100">
        {formatNumber(value, 0)}
      </span>
      {(band || provisional) && (
        <span className="text-[10px]" style={{ color: TEXT.muted }}>
          {provisional ? "provisional" : band?.replace("_", " ")}
        </span>
      )}
    </span>
  );
}
