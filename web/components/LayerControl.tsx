"use client";

import { strings } from "@/lib/strings";
import type { LayerVisibility } from "@/components/map/FleetMap";

/**
 * The single "Layers" control (Section 4d): vehicles, geofences, POIs and the
 * weather overlay each toggle independently.
 */
export function LayerControl({
  layers,
  onChange,
}: {
  layers: LayerVisibility;
  onChange: (layers: LayerVisibility) => void;
}) {
  const rows: [keyof LayerVisibility, string][] = [
    ["vehicles", strings.live.layerVehicles],
    ["geofences", strings.live.layerGeofences],
    ["pois", strings.live.layerPois],
    ["tasks", strings.live.layerTasks],
    ["weather", strings.live.layerWeather],
  ];

  return (
    <div className="rounded-lg border border-ink-600 bg-ink-800/95 p-3 shadow-lg backdrop-blur">
      <p className="fb-label mb-2">{strings.live.layers}</p>
      <ul className="space-y-1.5">
        {rows.map(([key, label]) => (
          <li key={key}>
            <label className="flex cursor-pointer items-center gap-2 text-xs text-ink-100">
              <input
                type="checkbox"
                checked={layers[key]}
                onChange={(e) => onChange({ ...layers, [key]: e.target.checked })}
                className="h-3.5 w-3.5 accent-electric"
              />
              {label}
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
