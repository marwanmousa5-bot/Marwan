import type { StyleSpecification } from "maplibre-gl";

/**
 * Basemap style.
 *
 * CARTO's dark basemap is used rather than standard OSM raster tiles: the
 * Live Tracking page is a control-room screen, and coloured status markers
 * need a low-contrast ground to read against. Attribution is required and is
 * rendered by the map's attribution control.
 *
 * Both providers ask that heavy production traffic use a paid plan or a
 * self-hosted tile server; swapping to one means changing this file only.
 */
export const TILE_ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>';

export function basemapStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {
      basemap: {
        type: "raster",
        tiles: [
          "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
          "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
          "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
        ],
        tileSize: 256,
        attribution: TILE_ATTRIBUTION,
      },
    },
    layers: [
      { id: "background", type: "background", paint: { "background-color": "#121417" } },
      { id: "basemap", type: "raster", source: "basemap" },
    ],
  };
}

/** Status colours, kept in one place so map and list can never disagree. */
export const STATUS_COLORS: Record<string, string> = {
  moving: "#2ECC71",
  idle: "#F5A623",
  alert: "#FF6B35",
  not_tracked: "#8A93A3",
};

/** Neutral cluster colour used when nothing inside needs attention. */
export const CLUSTER_NEUTRAL = "#1E90FF";
