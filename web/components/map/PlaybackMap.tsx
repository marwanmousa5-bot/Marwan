"use client";

/**
 * Trip History Playback map (Section 4c).
 *
 * Renders a completed trip's full recorded polyline with distinct start and
 * end markers, an animated vehicle marker driven by the parent's playback
 * position, and clickable markers for notable events.
 */

import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";

import type { TripEventMarker, TripPoint } from "@/lib/types";
import { basemapStyle } from "./mapStyle";

import "maplibre-gl/dist/maplibre-gl.css";

interface PlaybackMapProps {
  points: TripPoint[];
  events: TripEventMarker[];
  /** Index into `points` of the current playback position. */
  position: number;
  onSelectEvent: (event: TripEventMarker) => void;
}

const EVENT_COLORS: Record<string, string> = {
  harsh_braking: "#E74C3C",
  harsh_acceleration: "#F5A623",
  speeding: "#FF6B35",
  geofence_breach: "#1E90FF",
  idle_too_long: "#8A93A3",
};

export function PlaybackMap({
  points,
  events,
  position,
  onSelectEvent,
}: PlaybackMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const onSelectRef = useRef(onSelectEvent);

  useEffect(() => {
    onSelectRef.current = onSelectEvent;
  }, [onSelectEvent]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: basemapStyle(),
      center: [4.9041, 52.3676],
      zoom: 11,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    map.on("load", () => {
      const empty = { type: "FeatureCollection" as const, features: [] };

      map.addSource("route", { type: "geojson", data: empty });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: "route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#1E90FF", "line-width": 4, "line-opacity": 0.85 },
      });

      // The portion already played, drawn over the full route.
      map.addSource("route-travelled", { type: "geojson", data: empty });
      map.addLayer({
        id: "route-travelled-line",
        type: "line",
        source: "route-travelled",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#FFFFFF", "line-width": 2.5, "line-opacity": 0.6 },
      });

      map.addSource("endpoints", { type: "geojson", data: empty });
      map.addLayer({
        id: "endpoint-circles",
        type: "circle",
        source: "endpoints",
        paint: {
          "circle-radius": 7,
          "circle-color": ["get", "color"],
          "circle-stroke-width": 2,
          "circle-stroke-color": "#121417",
        },
      });

      map.addSource("events", { type: "geojson", data: empty });
      map.addLayer({
        id: "event-circles",
        type: "circle",
        source: "events",
        paint: {
          "circle-radius": 6,
          "circle-color": ["get", "color"],
          "circle-stroke-width": 2,
          "circle-stroke-color": "#121417",
        },
      });

      map.addSource("marker", { type: "geojson", data: empty });
      map.addLayer({
        id: "marker-halo",
        type: "circle",
        source: "marker",
        paint: { "circle-radius": 13, "circle-color": "#FF6B35", "circle-opacity": 0.25 },
      });
      map.addLayer({
        id: "marker-dot",
        type: "circle",
        source: "marker",
        paint: {
          "circle-radius": 6,
          "circle-color": "#FF6B35",
          "circle-stroke-width": 2,
          "circle-stroke-color": "#121417",
        },
      });

      setReady(true);
    });

    map.on("click", "event-circles", (event) => {
      const raw = event.features?.[0]?.properties?.payload;
      if (typeof raw === "string") {
        onSelectRef.current(JSON.parse(raw) as TripEventMarker);
      }
    });
    map.on("mouseenter", "event-circles", () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", "event-circles", () => {
      map.getCanvas().style.cursor = "";
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // --- route, endpoints and event markers -------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    const coordinates = points.map((p) => [p.lng, p.lat] as [number, number]);

    (map.getSource("route") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: coordinates.length
        ? [
            {
              type: "Feature",
              properties: {},
              geometry: { type: "LineString", coordinates },
            },
          ]
        : [],
    });

    (map.getSource("endpoints") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: coordinates.length
        ? [
            {
              type: "Feature",
              properties: { color: "#2ECC71", kind: "start" },
              geometry: { type: "Point", coordinates: coordinates[0] },
            },
            {
              type: "Feature",
              properties: { color: "#E74C3C", kind: "end" },
              geometry: {
                type: "Point",
                coordinates: coordinates[coordinates.length - 1],
              },
            },
          ]
        : [],
    });

    (map.getSource("events") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: events
        .filter((e) => e.lat != null && e.lng != null)
        .map((e) => ({
          type: "Feature" as const,
          properties: {
            color: EVENT_COLORS[e.event_type] ?? "#F5A623",
            payload: JSON.stringify(e),
          },
          geometry: {
            type: "Point" as const,
            coordinates: [e.lng as number, e.lat as number],
          },
        })),
    });

    if (coordinates.length > 1) {
      const bounds = coordinates.reduce(
        (acc, coord) => acc.extend(coord),
        new maplibregl.LngLatBounds(coordinates[0], coordinates[0]),
      );
      map.fitBounds(bounds, { padding: 60, duration: 600 });
    }
  }, [points, events, ready]);

  // --- the moving marker -------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || points.length === 0) return;

    const index = Math.max(0, Math.min(points.length - 1, Math.round(position)));
    const point = points[index];

    (map.getSource("marker") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {},
          geometry: { type: "Point", coordinates: [point.lng, point.lat] },
        },
      ],
    });

    (map.getSource("route-travelled") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features:
        index > 0
          ? [
              {
                type: "Feature",
                properties: {},
                geometry: {
                  type: "LineString",
                  coordinates: points
                    .slice(0, index + 1)
                    .map((p) => [p.lng, p.lat] as [number, number]),
                },
              },
            ]
          : [],
    });
  }, [position, points, ready]);

  return <div ref={containerRef} className="h-full w-full" />;
}
