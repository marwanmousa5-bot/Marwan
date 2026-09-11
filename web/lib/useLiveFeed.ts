"use client";

/**
 * Live WebSocket feed for the tracking page.
 *
 * Positions are merged into the vehicle list in place rather than refetching,
 * so the map never flickers. The socket reconnects with backoff; if it cannot
 * be established at all the caller falls back to polling the snapshot, so the
 * page degrades to stale-but-correct rather than blank.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { liveSocketUrl } from "./api";
import type { Alert, LiveMessage, LiveVehicle } from "./types";

type ConnectionState = "connecting" | "open" | "closed";

interface UseLiveFeedOptions {
  enabled: boolean;
  onAlert?: (alert: Alert) => void;
  onTripChange?: () => void;
}

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 20_000;
const HEARTBEAT_MS = 25_000;

export function useLiveFeed(
  vehicles: LiveVehicle[],
  setVehicles: (updater: (current: LiveVehicle[]) => LiveVehicle[]) => void,
  { enabled, onAlert, onTripChange }: UseLiveFeedOptions,
) {
  const [state, setState] = useState<ConnectionState>("closed");
  const socketRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const closedByUsRef = useRef(false);

  const handlersRef = useRef({ onAlert, onTripChange });
  useEffect(() => {
    handlersRef.current = { onAlert, onTripChange };
  }, [onAlert, onTripChange]);

  const connect = useCallback(() => {
    const url = liveSocketUrl();
    if (!url) return;

    setState("connecting");
    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onopen = () => {
      attemptRef.current = 0;
      setState("open");
      heartbeatRef.current = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) socket.send("ping");
      }, HEARTBEAT_MS);
    };

    socket.onmessage = (event) => {
      let message: LiveMessage;
      try {
        message = JSON.parse(event.data as string) as LiveMessage;
      } catch {
        return;
      }

      if (message.type === "position") {
        setVehicles((current) =>
          current.map((vehicle) =>
            vehicle.id === message.vehicle_id
              ? {
                  ...vehicle,
                  latitude: message.lat,
                  longitude: message.lng,
                  speed_kph: message.speed_kph,
                  heading: message.heading,
                  last_position_at: message.at,
                  // An alerting vehicle keeps its red status until the alert
                  // is dealt with; otherwise movement decides the colour.
                  live_status:
                    vehicle.active_alert_count > 0
                      ? "alert"
                      : message.moving
                        ? "moving"
                        : "idle",
                }
              : vehicle,
          ),
        );
        return;
      }

      if (message.type === "alert") {
        if (message.vehicle_id) {
          setVehicles((current) =>
            current.map((vehicle) =>
              vehicle.id === message.vehicle_id
                ? {
                    ...vehicle,
                    active_alert_count: vehicle.active_alert_count + 1,
                    live_status: vehicle.is_tracked ? "alert" : vehicle.live_status,
                  }
                : vehicle,
            ),
          );
        }
        handlersRef.current.onAlert?.({
          id: message.id,
          organization_id: "",
          rule_type: message.rule_type,
          severity: message.severity,
          status: message.status,
          title: message.title,
          message: message.message,
          vehicle_id: message.vehicle_id,
          driver_id: null,
          subject_type: null,
          subject_id: null,
          context: null,
          created_at: message.at,
        });
        return;
      }

      if (message.type === "trip.started" || message.type === "trip.ended") {
        handlersRef.current.onTripChange?.();
      }
    };

    socket.onclose = () => {
      setState("closed");
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      if (closedByUsRef.current) return;

      attemptRef.current += 1;
      const delay = Math.min(
        RECONNECT_MAX_MS,
        RECONNECT_BASE_MS * 2 ** (attemptRef.current - 1),
      );
      timerRef.current = setTimeout(connect, delay);
    };

    socket.onerror = () => socket.close();
  }, [setVehicles]);

  useEffect(() => {
    if (!enabled) return;
    closedByUsRef.current = false;
    connect();
    return () => {
      closedByUsRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      socketRef.current?.close();
    };
  }, [enabled, connect]);

  return { state, vehicleCount: vehicles.length };
}
