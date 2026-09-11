"use client";

/**
 * The live fleet map (Sections 4b and 4d).
 *
 * Responsibilities kept here: rendering vehicles, POIs, geofences and weather
 * as independently toggleable layers; clustering; smooth movement between
 * position updates; and the in-map geofence drawing mode. Data fetching and
 * socket handling live in the page above it, so this component stays a pure
 * view of whatever it is handed.
 *
 * Clustering uses MapLibre's built-in GeoJSON clustering, which *is*
 * Supercluster internally - the spec asks for a proven library rather than a
 * hand-rolled one, and this is that library without a second copy of it in
 * the bundle. Vehicles and POIs are separate sources, so they never merge
 * into one bubble.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import maplibregl, {
  type GeoJSONSource,
  type LngLatLike,
  type MapGeoJSONFeature,
} from "maplibre-gl";

import type { Geofence, LiveVehicle, Poi, WeatherZone } from "@/lib/types";
import { CLUSTER_NEUTRAL, STATUS_COLORS, basemapStyle } from "./mapStyle";
import { POI_COLORS, poiPin, vehicleArrow } from "./icons";

import "maplibre-gl/dist/maplibre-gl.css";

export type DrawMode = "none" | "polygon" | "circle";

export interface DrawnGeometry {
  shape: "polygon" | "circle";
  geometry:
    | { coordinates: [number, number][] }
    | { center: [number, number]; radius_m: number };
}

export interface LayerVisibility {
  vehicles: boolean;
  geofences: boolean;
  pois: boolean;
  weather: boolean;
}

interface FleetMapProps {
  vehicles: LiveVehicle[];
  geofences: Geofence[];
  pois: Poi[];
  weatherZones: WeatherZone[];
  layers: LayerVisibility;
  selectedVehicleId: string | null;
  onSelectVehicle: (vehicleId: string | null) => void;
  drawMode: DrawMode;
  onDrawComplete: (geometry: DrawnGeometry) => void;
  onMapClick?: (lngLat: { lng: number; lat: number }) => void;
}

const DEFAULT_CENTER: LngLatLike = [4.9041, 52.3676];
const DEFAULT_ZOOM = 11;
/** Position updates arrive every few seconds; ease across that window. */
const ANIMATION_MS = 2200;

interface AnimatedPosition {
  fromLng: number;
  fromLat: number;
  toLng: number;
  toLat: number;
  fromHeading: number;
  toHeading: number;
  startedAt: number;
  /** Wall-clock time of the update, used to fade the arrival pulse. */
  pulseAt: number;
}

/** Shortest-path angle interpolation, so 350° -> 10° does not spin backwards. */
function lerpAngle(from: number, to: number, t: number): number {
  const delta = ((((to - from) % 360) + 540) % 360) - 180;
  return (from + delta * t + 360) % 360;
}

function circlePolygon(
  center: [number, number],
  radiusM: number,
  steps = 64,
): [number, number][] {
  const [lng, lat] = center;
  const latRad = (lat * Math.PI) / 180;
  const dLat = (radiusM / 111_320) * (180 / Math.PI) * (Math.PI / 180);
  const dLng = dLat / Math.max(Math.cos(latRad), 1e-6);
  const ring: [number, number][] = [];
  for (let i = 0; i <= steps; i += 1) {
    const theta = (i / steps) * 2 * Math.PI;
    ring.push([lng + dLng * Math.cos(theta), lat + dLat * Math.sin(theta)]);
  }
  return ring;
}

function geofenceFeatures(geofences: Geofence[]) {
  return geofences
    .filter((fence) => fence.is_active)
    .map((fence) => {
      const ring =
        fence.shape === "circle" && fence.geometry.center
          ? circlePolygon(fence.geometry.center, fence.geometry.radius_m ?? 200)
          : [...(fence.geometry.coordinates ?? [])];
      if (ring.length && ring[0] !== ring[ring.length - 1]) ring.push(ring[0]);
      return {
        type: "Feature" as const,
        id: fence.id,
        properties: { id: fence.id, name: fence.name, color: fence.color },
        geometry: { type: "Polygon" as const, coordinates: [ring] },
      };
    });
}

export function FleetMap({
  vehicles,
  geofences,
  pois,
  weatherZones,
  layers,
  selectedVehicleId,
  onSelectVehicle,
  drawMode,
  onDrawComplete,
  onMapClick,
}: FleetMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);

  const animationsRef = useRef<Map<string, AnimatedPosition>>(new Map());
  const vehiclesRef = useRef<LiveVehicle[]>(vehicles);
  const frameRef = useRef<number | null>(null);

  // Draw-mode state lives in refs so map handlers registered once still see
  // the current values without re-binding on every render.
  const drawModeRef = useRef<DrawMode>(drawMode);
  const drawPointsRef = useRef<[number, number][]>([]);
  const circleCenterRef = useRef<[number, number] | null>(null);
  const onDrawCompleteRef = useRef(onDrawComplete);
  const onSelectRef = useRef(onSelectVehicle);
  const onMapClickRef = useRef(onMapClick);
  const [drawHint, setDrawHint] = useState<string | null>(null);

  useEffect(() => {
    drawModeRef.current = drawMode;
    drawPointsRef.current = [];
    circleCenterRef.current = null;
    setDrawHint(
      drawMode === "polygon"
        ? "Click to add points. Double-click to finish."
        : drawMode === "circle"
          ? "Click the centre, then click again to set the radius."
          : null,
    );
    const map = mapRef.current;
    if (map) {
      map.getCanvas().style.cursor = drawMode === "none" ? "" : "crosshair";
      const source = map.getSource("draft") as GeoJSONSource | undefined;
      source?.setData({ type: "FeatureCollection", features: [] });
    }
  }, [drawMode]);

  useEffect(() => {
    onDrawCompleteRef.current = onDrawComplete;
    onSelectRef.current = onSelectVehicle;
    onMapClickRef.current = onMapClick;
  }, [onDrawComplete, onSelectVehicle, onMapClick]);

  // --- map construction (once) ------------------------------------------
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: basemapStyle(),
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      attributionControl: { compact: true },
    });
    mapRef.current = map;

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    map.on("load", () => {
      for (const [status, color] of Object.entries(STATUS_COLORS)) {
        map.addImage(`vehicle-${status}`, vehicleArrow(color), { pixelRatio: 2 });
      }
      for (const [category, color] of Object.entries(POI_COLORS)) {
        map.addImage(`poi-${category}`, poiPin(color), { pixelRatio: 2 });
      }

      const empty = { type: "FeatureCollection" as const, features: [] };

      // --- weather (bottom of the stack: it is context, not content) ---
      map.addSource("weather", { type: "geojson", data: empty });
      map.addLayer({
        id: "weather-fill",
        type: "fill",
        source: "weather",
        paint: {
          "fill-color": [
            "match",
            ["get", "severity"],
            "critical",
            "#E74C3C",
            "#F5A623",
          ],
          "fill-opacity": 0.14,
        },
      });

      // --- geofences ---
      map.addSource("geofences", { type: "geojson", data: empty });
      map.addLayer({
        id: "geofence-fill",
        type: "fill",
        source: "geofences",
        paint: { "fill-color": ["get", "color"], "fill-opacity": 0.14 },
      });
      map.addLayer({
        id: "geofence-outline",
        type: "line",
        source: "geofences",
        paint: { "line-color": ["get", "color"], "line-width": 2 },
      });

      // --- the geometry currently being drawn ---
      map.addSource("draft", { type: "geojson", data: empty });
      map.addLayer({
        id: "draft-fill",
        type: "fill",
        source: "draft",
        paint: { "fill-color": "#1E90FF", "fill-opacity": 0.18 },
      });
      map.addLayer({
        id: "draft-line",
        type: "line",
        source: "draft",
        paint: { "line-color": "#1E90FF", "line-width": 2, "line-dasharray": [2, 1] },
      });

      // --- POIs: their own cluster layer, never mixed with vehicles ---
      map.addSource("pois", {
        type: "geojson",
        data: empty,
        cluster: true,
        clusterRadius: 46,
        clusterMaxZoom: 13,
      });
      map.addLayer({
        id: "poi-clusters",
        type: "circle",
        source: "pois",
        filter: ["has", "point_count"],
        paint: {
          "circle-color": "#2A2F38",
          "circle-radius": ["step", ["get", "point_count"], 15, 10, 19, 40, 24],
          "circle-stroke-width": 2,
          "circle-stroke-color": "#5B6371",
        },
      });
      map.addLayer({
        id: "poi-cluster-count",
        type: "symbol",
        source: "pois",
        filter: ["has", "point_count"],
        layout: {
          "text-field": ["get", "point_count_abbreviated"],
          "text-size": 12,
        },
        paint: { "text-color": "#E1E5EC" },
      });
      map.addLayer({
        id: "poi-markers",
        type: "symbol",
        source: "pois",
        filter: ["!", ["has", "point_count"]],
        layout: {
          "icon-image": ["concat", "poi-", ["get", "category"]],
          "icon-size": 0.6,
          "icon-allow-overlap": true,
          "icon-anchor": "bottom",
        },
      });

      // --- vehicles ---
      map.addSource("vehicles", {
        type: "geojson",
        data: empty,
        cluster: true,
        clusterRadius: 52,
        clusterMaxZoom: 13,
        // Worst-status-wins: these accumulate across everything inside a
        // bubble so a cluster can never hide an alerting vehicle.
        clusterProperties: {
          has_alert: ["max", ["get", "alert_flag"]],
          has_moving: ["max", ["get", "moving_flag"]],
        },
      });
      map.addLayer({
        id: "vehicle-pulse",
        type: "circle",
        source: "vehicles",
        filter: ["!", ["has", "point_count"]],
        paint: {
          "circle-radius": ["get", "pulse_radius"],
          "circle-color": ["get", "color"],
          "circle-opacity": ["get", "pulse_opacity"],
        },
      });
      map.addLayer({
        id: "vehicle-clusters",
        type: "circle",
        source: "vehicles",
        filter: ["has", "point_count"],
        paint: {
          "circle-color": [
            "case",
            [">", ["get", "has_alert"], 0],
            STATUS_COLORS.alert,
            [">", ["get", "has_moving"], 0],
            STATUS_COLORS.moving,
            CLUSTER_NEUTRAL,
          ],
          "circle-radius": ["step", ["get", "point_count"], 17, 10, 22, 40, 28],
          "circle-stroke-width": 2,
          "circle-stroke-color": "rgba(18,20,23,0.8)",
        },
      });
      map.addLayer({
        id: "vehicle-cluster-count",
        type: "symbol",
        source: "vehicles",
        filter: ["has", "point_count"],
        layout: {
          "text-field": ["get", "point_count_abbreviated"],
          "text-size": 13,
        },
        paint: { "text-color": "#121417" },
      });
      map.addLayer({
        id: "vehicle-markers",
        type: "symbol",
        source: "vehicles",
        filter: ["!", ["has", "point_count"]],
        layout: {
          "icon-image": ["concat", "vehicle-", ["get", "status"]],
          "icon-size": ["case", ["get", "selected"], 0.78, 0.62],
          "icon-rotate": ["get", "heading"],
          "icon-rotation-alignment": "map",
          "icon-allow-overlap": true,
          "text-field": ["get", "label"],
          "text-offset": [0, 1.5],
          "text-size": 11,
          "text-optional": true,
          "text-allow-overlap": false,
        },
        paint: {
          "text-color": "#E1E5EC",
          "text-halo-color": "#121417",
          "text-halo-width": 1.2,
        },
      });

      setReady(true);
    });

    // --- interaction ---
    map.on("click", "vehicle-markers", (event) => {
      const feature = event.features?.[0] as MapGeoJSONFeature | undefined;
      const id = feature?.properties?.id as string | undefined;
      if (id) onSelectRef.current(id);
    });

    map.on("click", "vehicle-clusters", async (event) => {
      const feature = event.features?.[0];
      const clusterId = feature?.properties?.cluster_id;
      if (clusterId === undefined) return;
      const source = map.getSource("vehicles") as GeoJSONSource;
      const zoom = await source.getClusterExpansionZoom(Number(clusterId));
      map.easeTo({
        center: (feature!.geometry as GeoJSON.Point).coordinates as [number, number],
        zoom,
      });
    });

    for (const layer of ["vehicle-markers", "vehicle-clusters", "poi-markers"]) {
      map.on("mouseenter", layer, () => {
        if (drawModeRef.current === "none") map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", layer, () => {
        if (drawModeRef.current === "none") map.getCanvas().style.cursor = "";
      });
    }

    map.on("click", (event) => {
      const mode = drawModeRef.current;
      const point: [number, number] = [event.lngLat.lng, event.lngLat.lat];

      if (mode === "none") {
        onMapClickRef.current?.({ lng: point[0], lat: point[1] });
        return;
      }

      if (mode === "polygon") {
        drawPointsRef.current = [...drawPointsRef.current, point];
        updateDraft(map, drawPointsRef.current);
        return;
      }

      // circle: first click sets the centre, second sets the radius
      if (!circleCenterRef.current) {
        circleCenterRef.current = point;
        return;
      }
      const center = circleCenterRef.current;
      const radius = haversineMeters(center, point);
      circleCenterRef.current = null;
      onDrawCompleteRef.current({
        shape: "circle",
        geometry: { center, radius_m: Math.max(25, Math.round(radius)) },
      });
    });

    map.on("mousemove", (event) => {
      const mode = drawModeRef.current;
      if (mode === "polygon" && drawPointsRef.current.length > 0) {
        updateDraft(map, [
          ...drawPointsRef.current,
          [event.lngLat.lng, event.lngLat.lat],
        ]);
      } else if (mode === "circle" && circleCenterRef.current) {
        const radius = haversineMeters(circleCenterRef.current, [
          event.lngLat.lng,
          event.lngLat.lat,
        ]);
        updateDraft(map, circlePolygon(circleCenterRef.current, Math.max(25, radius)));
      }
    });

    map.on("dblclick", (event) => {
      if (drawModeRef.current !== "polygon") return;
      event.preventDefault();
      const points = drawPointsRef.current;
      if (points.length >= 3) {
        onDrawCompleteRef.current({ shape: "polygon", geometry: { coordinates: points } });
      }
      drawPointsRef.current = [];
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // --- vehicle data + smooth animation ----------------------------------
  useEffect(() => {
    vehiclesRef.current = vehicles;
    const now = performance.now();
    const animations = animationsRef.current;

    for (const vehicle of vehicles) {
      if (vehicle.latitude == null || vehicle.longitude == null) continue;
      const existing = animations.get(vehicle.id);
      if (!existing) {
        animations.set(vehicle.id, {
          fromLng: vehicle.longitude,
          fromLat: vehicle.latitude,
          toLng: vehicle.longitude,
          toLat: vehicle.latitude,
          fromHeading: vehicle.heading ?? 0,
          toHeading: vehicle.heading ?? 0,
          startedAt: now - ANIMATION_MS,
          pulseAt: 0,
        });
        continue;
      }
      const moved =
        existing.toLng !== vehicle.longitude || existing.toLat !== vehicle.latitude;
      if (!moved) continue;

      // Continue from wherever the marker currently is, not from the last
      // target, so a mid-flight update does not snap.
      const progress = Math.min(1, (now - existing.startedAt) / ANIMATION_MS);
      animations.set(vehicle.id, {
        fromLng: existing.fromLng + (existing.toLng - existing.fromLng) * progress,
        fromLat: existing.fromLat + (existing.toLat - existing.fromLat) * progress,
        toLng: vehicle.longitude,
        toLat: vehicle.latitude,
        fromHeading: lerpAngle(existing.fromHeading, existing.toHeading, progress),
        toHeading: vehicle.heading ?? existing.toHeading,
        startedAt: now,
        pulseAt: now,
      });
    }

    for (const id of [...animations.keys()]) {
      if (!vehicles.some((v) => v.id === id)) animations.delete(id);
    }
  }, [vehicles]);

  const renderVehicles = useCallback(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("vehicles")) return;

    const now = performance.now();
    const features = vehiclesRef.current
      .filter((v) => v.latitude != null && v.longitude != null)
      .map((vehicle) => {
        const anim = animationsRef.current.get(vehicle.id);
        let lng = vehicle.longitude as number;
        let lat = vehicle.latitude as number;
        let heading = vehicle.heading ?? 0;
        let pulse = 0;

        if (anim) {
          const t = Math.min(1, (now - anim.startedAt) / ANIMATION_MS);
          // Ease-out: vehicles decelerate into their reported position rather
          // than arriving at constant speed and stopping dead.
          const eased = 1 - (1 - t) * (1 - t);
          lng = anim.fromLng + (anim.toLng - anim.fromLng) * eased;
          lat = anim.fromLat + (anim.toLat - anim.fromLat) * eased;
          heading = lerpAngle(anim.fromHeading, anim.toHeading, eased);
          if (anim.pulseAt) {
            const age = (now - anim.pulseAt) / 900;
            if (age < 1) pulse = 1 - age;
          }
        }

        const status = vehicle.live_status;
        return {
          type: "Feature" as const,
          id: vehicle.id,
          properties: {
            id: vehicle.id,
            label: vehicle.name,
            status,
            heading,
            color: STATUS_COLORS[status] ?? CLUSTER_NEUTRAL,
            selected: vehicle.id === selectedVehicleId,
            // Numeric flags so cluster "max" accumulators can use them.
            alert_flag: status === "alert" ? 1 : 0,
            moving_flag: status === "moving" ? 1 : 0,
            pulse_radius: 14 + pulse * 16,
            pulse_opacity: pulse * 0.35,
          },
          geometry: { type: "Point" as const, coordinates: [lng, lat] },
        };
      });

    (map.getSource("vehicles") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features,
    });
  }, [selectedVehicleId]);

  useEffect(() => {
    if (!ready) return;
    const step = () => {
      renderVehicles();
      frameRef.current = requestAnimationFrame(step);
    };
    frameRef.current = requestAnimationFrame(step);
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [ready, renderVehicles]);

  // --- other layers ------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("geofences") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: geofenceFeatures(geofences),
    });
  }, [geofences, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("pois") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: pois.map((poi) => ({
        type: "Feature" as const,
        id: poi.id,
        properties: { id: poi.id, name: poi.name, category: poi.category },
        geometry: {
          type: "Point" as const,
          coordinates: [poi.longitude, poi.latitude],
        },
      })),
    });
  }, [pois, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("weather") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: weatherZones.map((zone) => ({
        type: "Feature" as const,
        id: zone.id,
        properties: { severity: zone.severity, condition: zone.condition },
        geometry: {
          type: "Polygon" as const,
          coordinates: [
            circlePolygon([zone.longitude, zone.latitude], zone.radius_m),
          ],
        },
      })),
    });
  }, [weatherZones, ready]);

  // --- layer toggles -----------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const groups: Record<keyof LayerVisibility, string[]> = {
      vehicles: [
        "vehicle-markers",
        "vehicle-clusters",
        "vehicle-cluster-count",
        "vehicle-pulse",
      ],
      geofences: ["geofence-fill", "geofence-outline"],
      pois: ["poi-markers", "poi-clusters", "poi-cluster-count"],
      weather: ["weather-fill"],
    };
    for (const [group, layerIds] of Object.entries(groups)) {
      const visible = layers[group as keyof LayerVisibility];
      for (const layerId of layerIds) {
        if (map.getLayer(layerId)) {
          map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
        }
      }
    }
  }, [layers, ready]);

  // --- keep the map in sync with the sidebar selection -------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !selectedVehicleId) return;
    const vehicle = vehicles.find((v) => v.id === selectedVehicleId);
    if (!vehicle || vehicle.latitude == null || vehicle.longitude == null) return;
    map.easeTo({
      center: [vehicle.longitude, vehicle.latitude],
      zoom: Math.max(map.getZoom(), 14),
      duration: 700,
    });
    // Only react to a change of selection, not to every position tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedVehicleId, ready]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />
      {drawHint && (
        <div className="pointer-events-none absolute left-1/2 top-4 -translate-x-1/2 rounded-full bg-electric px-4 py-1.5 text-xs font-medium text-white shadow-lg">
          {drawHint}
        </div>
      )}
    </div>
  );
}

function updateDraft(map: maplibregl.Map, points: [number, number][]) {
  const source = map.getSource("draft") as GeoJSONSource | undefined;
  if (!source) return;
  if (points.length < 2) {
    source.setData({ type: "FeatureCollection", features: [] });
    return;
  }
  const ring = [...points];
  if (ring.length > 2) ring.push(ring[0]);
  source.setData({
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {},
        geometry:
          ring.length > 3
            ? { type: "Polygon", coordinates: [ring] }
            : { type: "LineString", coordinates: ring },
      },
    ],
  });
}

function haversineMeters(a: [number, number], b: [number, number]): number {
  const R = 6_371_000;
  const dLat = ((b[1] - a[1]) * Math.PI) / 180;
  const dLng = ((b[0] - a[0]) * Math.PI) / 180;
  const lat1 = (a[1] * Math.PI) / 180;
  const lat2 = (b[1] * Math.PI) / 180;
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}
