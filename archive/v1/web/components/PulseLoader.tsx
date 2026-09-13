import { strings } from "@/lib/strings";

/** Full-screen loading state carrying the heartbeat motif (Section 1). */
export function PulseLoader({ label }: { label?: string }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-ink-900">
      <div className="relative flex h-5 w-5 items-center justify-center">
        <span className="absolute h-5 w-5 rounded-full bg-coral/40 animate-pulsering" />
        <span className="h-2.5 w-2.5 rounded-full bg-coral animate-heartbeat" />
      </div>
      <p className="text-sm text-ink-300">{label ?? strings.common.loading}</p>
    </div>
  );
}
