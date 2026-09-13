import type { VehicleLiveStatus } from "@/lib/types";

/**
 * Live-status dot for the map and the vehicle sidebar (Section 4b).
 * green = moving, yellow = idle, red = active alert, grey = not tracked.
 * Only the alert state pulses - the motion is the signal, so it has to stay
 * rare enough to mean something.
 */
const STATUS_STYLES: Record<
  VehicleLiveStatus,
  { dot: string; label: string; ring: string }
> = {
  moving: { dot: "bg-success", label: "Moving", ring: "bg-success/40" },
  idle: { dot: "bg-warning", label: "Stopped", ring: "bg-warning/40" },
  alert: { dot: "bg-coral", label: "Alert", ring: "bg-coral/40" },
  not_tracked: { dot: "bg-ink-400", label: "Not tracked", ring: "bg-ink-400/30" },
};

export function StatusDot({
  status,
  withLabel = false,
}: {
  status: VehicleLiveStatus;
  withLabel?: boolean;
}) {
  const style = STATUS_STYLES[status];
  return (
    <span className="inline-flex items-center gap-2">
      <span className="relative flex h-2.5 w-2.5 items-center justify-center">
        {status === "alert" && (
          <span
            className={`absolute h-2.5 w-2.5 rounded-full ${style.ring} animate-pulsering`}
          />
        )}
        <span className={`h-2.5 w-2.5 rounded-full ${style.dot}`} />
      </span>
      {withLabel && <span className="text-xs text-ink-300">{style.label}</span>}
    </span>
  );
}

export function statusLabel(status: VehicleLiveStatus): string {
  return STATUS_STYLES[status].label;
}
