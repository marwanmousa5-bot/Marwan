"use client";

import { strings } from "@/lib/strings";

/** Offset pager for the long, filterable lists (audit log, sign-in activity). */
export function Pager({
  offset,
  total,
  pageSize,
  onChange,
}: {
  offset: number;
  total: number;
  pageSize: number;
  onChange: (offset: number) => void;
}) {
  const to = Math.min(offset + pageSize, total);
  return (
    <div className="flex items-center justify-between text-xs text-ink-400">
      <span className="fb-numeric">
        {strings.audit.showing} {total === 0 ? 0 : offset + 1}–{to} of {total}
      </span>
      <div className="flex gap-2">
        <button
          onClick={() => onChange(Math.max(0, offset - pageSize))}
          disabled={offset === 0}
          className="fb-button-ghost !py-1 text-xs disabled:opacity-40"
        >
          {strings.audit.newer}
        </button>
        <button
          onClick={() => onChange(offset + pageSize)}
          disabled={to >= total}
          className="fb-button-ghost !py-1 text-xs disabled:opacity-40"
        >
          {strings.audit.older}
        </button>
      </div>
    </div>
  );
}
