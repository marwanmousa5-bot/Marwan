import type { ReactNode } from "react";

import { TEXT } from "./tokens";

/**
 * A headline number. The right form for a single current value - a one-bar
 * bar chart would say the same thing with more ink.
 */
export function StatTile({
  label,
  value,
  unit,
  hint,
  tone = "neutral",
  hero = false,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: string;
  tone?: "neutral" | "good" | "warning" | "critical";
  hero?: boolean;
}) {
  const toneClass =
    tone === "good"
      ? "text-success"
      : tone === "warning"
        ? "text-warning"
        : tone === "critical"
          ? "text-danger"
          : "text-white";

  return (
    <div className="fb-card px-4 py-3">
      <p className="fb-label">{label}</p>
      <p
        className={`fb-numeric mt-1 font-semibold ${toneClass} ${
          hero ? "text-4xl" : "text-2xl"
        }`}
      >
        {value}
        {unit && (
          <span
            className="ml-1 text-sm font-normal"
            style={{ color: TEXT.muted }}
          >
            {unit}
          </span>
        )}
      </p>
      {hint && (
        <p className="mt-0.5 text-[11px]" style={{ color: TEXT.muted }}>
          {hint}
        </p>
      )}
    </div>
  );
}
