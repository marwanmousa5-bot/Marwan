"use client";

/**
 * Trip History Playback (Section 4c).
 *
 * Distinct from the Live Tracking home page: this replays a *completed* trip
 * from its persisted position samples. Vehicle + date pick a trip list;
 * selecting a trip loads its full route, and the transport controls animate a
 * marker along it with a scrubber synced to playback.
 */

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";

import { api } from "@/lib/api";
import { strings } from "@/lib/strings";
import type { Page, Trip, TripEventMarker, TripPlayback, Vehicle } from "@/lib/types";

const PlaybackMap = dynamic(
  () => import("@/components/map/PlaybackMap").then((m) => m.PlaybackMap),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center bg-ink-800 text-sm text-ink-400">
        {strings.common.loading}
      </div>
    ),
  },
);

const SPEEDS = [1, 5, 20] as const;
/** Samples advanced per second at 1x - the feed emits roughly this often. */
const BASE_SAMPLES_PER_SECOND = 2;

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function TripHistory() {
  const params = useSearchParams();

  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [vehicleId, setVehicleId] = useState<string>(params.get("vehicle") ?? "");
  const [date, setDate] = useState<string>(todayIso());
  const [trips, setTrips] = useState<Trip[]>([]);
  const [playback, setPlayback] = useState<TripPlayback | null>(null);
  const [selectedTripId, setSelectedTripId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [position, setPosition] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(5);
  const frameRef = useRef<number | null>(null);
  const lastFrameRef = useRef<number>(0);

  useEffect(() => {
    (async () => {
      const page = await api.get<Page<Vehicle>>("/vehicles?limit=200");
      setVehicles(page.items);
      if (!vehicleId && page.items.length > 0) {
        // Default to a tracked vehicle: an untracked one has no history at
        // all, so landing on it makes the page look broken.
        const tracked = page.items.find((v) => v.is_tracked);
        setVehicleId((tracked ?? page.items[0]).id);
      }
    })().catch(() => setError("We could not load your vehicles."));
    // Only on mount: later changes come from the selector.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadTrips = useCallback(async () => {
    if (!vehicleId) return;
    setLoading(true);
    try {
      const page = await api.get<Page<Trip>>(
        `/trips?vehicle_id=${vehicleId}&date_from=${date}&date_to=${date}&limit=100`,
      );
      setTrips(page.items);
      setError(null);
    } catch {
      setError("We could not load trips for that day.");
    } finally {
      setLoading(false);
    }
  }, [vehicleId, date]);

  useEffect(() => {
    setPlayback(null);
    setSelectedTripId(null);
    setPlaying(false);
    void loadTrips();
  }, [loadTrips]);

  async function selectTrip(tripId: string) {
    setSelectedTripId(tripId);
    setPlaying(false);
    setPosition(0);
    try {
      setPlayback(await api.get<TripPlayback>(`/trips/${tripId}/playback`));
    } catch {
      setError("We could not load that trip's route.");
    }
  }

  // --- playback loop -----------------------------------------------------
  useEffect(() => {
    if (!playing || !playback || playback.points.length === 0) return;

    lastFrameRef.current = performance.now();
    const step = (now: number) => {
      const elapsed = (now - lastFrameRef.current) / 1000;
      lastFrameRef.current = now;
      setPosition((current) => {
        const next = current + elapsed * BASE_SAMPLES_PER_SECOND * speed;
        if (next >= playback.points.length - 1) {
          setPlaying(false);
          return playback.points.length - 1;
        }
        return next;
      });
      frameRef.current = requestAnimationFrame(step);
    };
    frameRef.current = requestAnimationFrame(step);

    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [playing, playback, speed]);

  const currentPoint =
    playback && playback.points.length > 0
      ? playback.points[
          Math.max(0, Math.min(playback.points.length - 1, Math.round(position)))
        ]
      : null;

  function jumpToEvent(event: TripEventMarker) {
    if (!playback) return;
    // Land on the sample nearest the event's timestamp.
    const target = new Date(event.at).getTime();
    let best = 0;
    let bestDelta = Number.POSITIVE_INFINITY;
    playback.points.forEach((point, index) => {
      const delta = Math.abs(new Date(point.at).getTime() - target);
      if (delta < bestDelta) {
        bestDelta = delta;
        best = index;
      }
    });
    setPlaying(false);
    setPosition(best);
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-white">{strings.history.title}</h1>
        <p className="mt-1 text-sm text-ink-300">{strings.history.subtitle}</p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1.5">
          <span className="fb-label">{strings.history.selectVehicle}</span>
          <select
            value={vehicleId}
            onChange={(e) => setVehicleId(e.target.value)}
            className="fb-input min-w-56"
          >
            {vehicles.map((vehicle) => (
              <option key={vehicle.id} value={vehicle.id}>
                {vehicle.name} · {vehicle.license_plate}
                {vehicle.is_tracked ? "" : " (not tracked)"}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1.5">
          <span className="fb-label">{strings.history.selectDate}</span>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="fb-input"
          />
        </label>
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[20rem_1fr]">
        <section className="fb-card max-h-[28rem] overflow-y-auto">
          <h2 className="border-b border-ink-600/70 px-4 py-2.5 text-sm font-semibold text-white">
            Trips
          </h2>
          {loading ? (
            <p className="px-4 py-5 text-xs text-ink-400">{strings.common.loading}</p>
          ) : trips.length === 0 ? (
            <p className="px-4 py-5 text-xs text-ink-400">{strings.history.noTrips}</p>
          ) : (
            <ul className="divide-y divide-ink-600/50">
              {trips.map((trip) => (
                <li key={trip.id}>
                  <button
                    onClick={() => selectTrip(trip.id)}
                    className={`w-full px-4 py-3 text-left transition ${
                      trip.id === selectedTripId
                        ? "bg-electric/10"
                        : "hover:bg-ink-700/40"
                    }`}
                  >
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="fb-numeric text-xs text-ink-50">
                        {new Date(trip.started_at).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                        {trip.ended_at &&
                          ` – ${new Date(trip.ended_at).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}`}
                      </span>
                      <span className="fb-numeric text-xs text-ink-300">
                        {trip.distance_km.toFixed(1)} km
                      </span>
                    </span>
                    <span className="fb-numeric mt-0.5 block text-[11px] text-ink-400">
                      {formatDuration(trip.duration_seconds)} · avg{" "}
                      {Math.round(trip.average_speed_kph)} km/h · max{" "}
                      {Math.round(trip.max_speed_kph)} km/h
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="fb-card overflow-hidden">
          <div className="h-[24rem]">
            {playback && playback.points.length > 0 ? (
              <PlaybackMap
                points={playback.points}
                events={playback.events}
                position={position}
                onSelectEvent={jumpToEvent}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-ink-400">
                Select a trip to replay it.
              </div>
            )}
          </div>

          {playback && playback.points.length > 0 && (
            <div className="space-y-3 border-t border-ink-600/70 p-4">
              <div className="flex flex-wrap items-center gap-3">
                <button
                  onClick={() => setPlaying((p) => !p)}
                  className="fb-button-primary !py-1.5 min-w-24"
                >
                  {playing ? strings.history.pause : strings.history.play}
                </button>

                <div className="flex items-center gap-1">
                  <span className="fb-label !normal-case">{strings.history.speed}</span>
                  {SPEEDS.map((value) => (
                    <button
                      key={value}
                      onClick={() => setSpeed(value)}
                      className={`rounded px-2 py-1 text-[11px] transition ${
                        speed === value
                          ? "bg-electric text-white"
                          : "bg-ink-700 text-ink-300 hover:bg-ink-600"
                      }`}
                    >
                      {value}x
                    </button>
                  ))}
                </div>

                {currentPoint && (
                  <span className="fb-numeric ml-auto text-xs text-ink-300">
                    {new Date(currentPoint.at).toLocaleTimeString()} ·{" "}
                    {Math.round(currentPoint.speed_kph)} km/h
                  </span>
                )}
              </div>

              <div className="relative">
                <input
                  type="range"
                  min={0}
                  max={playback.points.length - 1}
                  step={1}
                  value={Math.round(position)}
                  onChange={(e) => {
                    setPlaying(false);
                    setPosition(Number(e.target.value));
                  }}
                  aria-label="Playback position"
                  className="w-full accent-electric"
                />
                {/* Event markers on the timeline, clickable to jump there. */}
                <div className="pointer-events-none absolute inset-x-0 top-0 h-full">
                  {playback.events.map((event) => {
                    const target = new Date(event.at).getTime();
                    const first = new Date(playback.points[0].at).getTime();
                    const last = new Date(
                      playback.points[playback.points.length - 1].at,
                    ).getTime();
                    const span = Math.max(1, last - first);
                    const pct = Math.min(
                      100,
                      Math.max(0, ((target - first) / span) * 100),
                    );
                    return (
                      <button
                        key={event.id}
                        onClick={() => jumpToEvent(event)}
                        title={`${event.event_type.replace(/_/g, " ")} at ${new Date(
                          event.at,
                        ).toLocaleTimeString()}`}
                        style={{ left: `${pct}%` }}
                        className="pointer-events-auto absolute -top-1 h-2.5 w-2.5 -translate-x-1/2 rounded-full border border-ink-900 bg-coral"
                      />
                    );
                  })}
                </div>
              </div>

              <div className="flex items-center justify-between text-[11px] text-ink-400">
                <span>
                  {strings.history.start}{" "}
                  {new Date(playback.points[0].at).toLocaleTimeString()}
                </span>
                <span>
                  {playback.events.length} event
                  {playback.events.length === 1 ? "" : "s"}
                </span>
                <span>
                  {strings.history.end}{" "}
                  {new Date(
                    playback.points[playback.points.length - 1].at,
                  ).toLocaleTimeString()}
                </span>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

export default function TripHistoryPage() {
  return (
    <Suspense>
      <TripHistory />
    </Suspense>
  );
}
