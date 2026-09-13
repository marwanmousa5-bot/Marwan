"use client";

/**
 * A small map for choosing a task destination (Section 4f).
 *
 * Reuses the POI/search infrastructure's idea: the dispatcher drops the pin
 * by clicking, rather than typing coordinates. The preview route, once
 * computed, is drawn so they can sanity-check it before assigning.
 */

import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";

import type { Poi } from "@/lib/types";
import { basemapStyle } from "./mapStyle";
import { POI_COLORS, poiPin } from "./icons";

import "maplibre-gl/dist/maplibre-gl.css";

interface DestinationPickerProps {
  destination: { lat: number; lng: number } | null;
  onPick: (point: { lat: number; lng: number }) => void;
  pois: Poi[];
  /** Encoded polyline (precision 5) from the route preview. */
  routePolyline?: string | null;
}

/** Decode an OSRM polyline (precision 5) into [lng, lat] pairs. */
function decodePolyline(encoded: string): [number, number][] {
  const points: [number, number][] = [];
  let index = 0;
  let lat = 0;
  let lng = 0;

  while (index < encoded.length) {
    let result = 0;
    let shift = 0;
    let byte: number;
    do {
      byte = encoded.charCodeAt(index++) - 63;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20);
    lat += result & 1 ? ~(result >> 1) : result >> 1;

    result = 0;
    shift = 0;
    do {
      byte = encoded.charCodeAt(index++) - 63;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20);
    lng += result & 1 ? ~(result >> 1) : result >> 1;

    points.push([lng / 1e5, lat / 1e5]);
  }
  return points;
}

export function DestinationPicker({
  destination,
  onPick,
  pois,
  routePolyline,
}: DestinationPickerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const onPickRef = useRef(onPick);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    onPickRef.current = onPick;
  }, [onPick]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: basemapStyle(),
      center: [4.9041, 52.3676],
      zoom: 10,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.getCanvas().style.cursor = "crosshair";

    map.on("load", () => {
      const empty = { type: "FeatureCollection" as const, features: [] };

      for (const [category, color] of Object.entries(POI_COLORS)) {
        map.addImage(`pick-poi-${category}`, poiPin(color), { pixelRatio: 2 });
      }

      map.addSource("preview-route", { type: "geojson", data: empty });
      map.addLayer({
        id: "preview-route-line",
        type: "line",
        source: "preview-route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#1E90FF", "line-width": 4, "line-opacity": 0.9 },
      });

      map.addSource("pick-pois", { type: "geojson", data: empty });
      map.addLayer({
        id: "pick-poi-markers",
        type: "symbol",
        source: "pick-pois",
        layout: {
          "icon-image": ["concat", "pick-poi-", ["get", "category"]],
          "icon-size": 0.55,
          "icon-anchor": "bottom",
          "icon-allow-overlap": true,
        },
      });

      map.addSource("destination", { type: "geojson", data: empty });
      map.addLayer({
        id: "destination-marker",
        type: "circle",
        source: "destination",
        paint: {
          "circle-radius": 9,
          "circle-color": "#FF6B35",
          "circle-stroke-width": 3,
          "circle-stroke-color": "#121417",
        },
      });

      setReady(true);
    });

    map.on("click", (event) => {
      onPickRef.current({ lat: event.lngLat.lat, lng: event.lngLat.lng });
    });

    // Clicking a saved place is faster than hunting for its exact pin.
    map.on("click", "pick-poi-markers", (event) => {
      const feature = event.features?.[0];
      if (!feature) return;
      const [lng, lat] = (feature.geometry as GeoJSON.Point).coordinates;
      onPickRef.current({ lat, lng });
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("pick-pois") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: pois.map((poi) => ({
        type: "Feature" as const,
        properties: { category: poi.category, name: poi.name },
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
    (map.getSource("destination") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: destination
        ? [
            {
              type: "Feature",
              properties: {},
              geometry: {
                type: "Point",
                coordinates: [destination.lng, destination.lat],
              },
            },
          ]
        : [],
    });
  }, [destination, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const coordinates = routePolyline ? decodePolyline(routePolyline) : [];
    (map.getSource("preview-route") as GeoJSONSource).setData({
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
    if (coordinates.length > 1) {
      const bounds = coordinates.reduce(
        (acc, coord) => acc.extend(coord),
        new maplibregl.LngLatBounds(coordinates[0], coordinates[0]),
      );
      map.fitBounds(bounds, { padding: 50, duration: 600 });
    }
  }, [routePolyline, ready]);

  return <div ref={containerRef} className="h-full w-full" />;
}
