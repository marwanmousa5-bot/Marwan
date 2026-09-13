import { strings } from "@/lib/strings";

/** Wordmark with the heartbeat glyph. */
export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <svg
        viewBox="0 0 32 32"
        aria-hidden="true"
        className="h-7 w-7 shrink-0"
        fill="none"
      >
        <rect width="32" height="32" rx="9" fill="#1E90FF" />
        <path
          d="M5 17h5l2.5-6 4 12 3-9 2 3h5.5"
          stroke="#FFFFFF"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {!compact && (
        <span className="text-base font-semibold tracking-tight text-white">
          {strings.brand.name}
        </span>
      )}
    </span>
  );
}
