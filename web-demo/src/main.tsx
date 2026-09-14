// Boot: load the real OSM geometry and the routing graph, build the demo
// tenant, then start the clock.

import { createRoot } from 'react-dom/client';
import { StrictMode, useEffect, useState } from 'react';
import { buildWorld, type RawPlace } from './engine/seed';
import { StreetGraph, type RawGraph } from './engine/router';
import { Simulation } from './engine/sim';
import { setStore, type Store } from './engine/store';
import { App } from './ui/App';
import type { BaseData } from './ui/map/style';

const STEPS = [
  'Loading Helsinki street network',
  'Building the routing graph',
  'Creating the demo fleet',
  'Replaying four months of operations',
  'Starting the live feed',
];

function Boot() {
  const [step, setStep] = useState(0);
  const [ready, setReady] = useState<{ store: Store; sim: Simulation; base: BaseData } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const tick = async (n: number) => {
          if (cancelled) return;
          setStep(n);
          await new Promise((r) => setTimeout(r, 16));
        };

        await tick(0);
        const [roads, paths, rail, buildings, water, landuse, places, graphRaw, glyphs] =
          await Promise.all([
            fetchJson('data/roads.geojson'),
            fetchJson('data/paths.geojson'),
            fetchJson('data/rail.geojson'),
            fetchJson('data/buildings.geojson'),
            fetchJson('data/water.geojson'),
            fetchJson('data/landuse.geojson'),
            fetchJson('data/places.json'),
            fetchJson('data/graph.json'),
            fetchJson('data/glyphs.json'),
          ]);

        // Map labels are drawn from SDF glyphs we generated from Noto Sans, served
        // through a custom protocol so the page needs no font CDN.
        const ml = window.maplibregl;
        ml.setWorkerUrl('vendor/maplibre-gl-csp-worker.js');
        ml.addProtocol('fbfont', async (params: { url: string }) => {
          const key = params.url.replace('fbfont://', '');
          const hit = (glyphs as Record<string, string>)[key]
            ?? (glyphs as Record<string, string>)[
              `NotoSans-Regular/${key.split('/')[1] ?? '0-255'}`];
          if (!hit) return { data: new ArrayBuffer(0) };
          const bin = atob(hit);
          const bytes = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
          return { data: bytes.buffer };
        });

        await tick(1);
        const graph = new StreetGraph(graphRaw as RawGraph);

        await tick(2);
        const now = Date.now();
        await tick(3);
        const store = buildWorld(graph, places as RawPlace[], now);
        setStore(store);
        // Exposed deliberately: it lets an operator inspect the exact state the UI is
        // rendering from the browser console, and it is how this build is verified.
        (window as unknown as Record<string, unknown>).__fb = store;

        await tick(4);
        const sim = new Simulation(store);
        const base: BaseData = { roads, paths, rail, buildings, water, landuse };
        if (!cancelled) setReady({ store, sim, base });
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Unknown error while loading FleetBeat.');
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (error) {
    return (
      <div className="boot">
        <div className="boot-inner">
          <strong style={{ fontSize: 15 }}>FleetBeat could not start</strong>
          <p style={{ maxWidth: '46ch', color: 'var(--ink-3)', fontSize: 13 }}>{error}</p>
          <button className="btn" data-variant="primary" onClick={() => location.reload()}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="boot">
        <div className="boot-inner">
          <span className="logo-mark" style={{ width: 40, height: 40 }} aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 16 16" fill="none" stroke="#fff"
                 strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M1.5 8h3l1.5-3.5L9 12l1.5-4h4" />
            </svg>
          </span>
          <div>
            <div style={{ fontWeight: 700, fontSize: 17, letterSpacing: '-.02em' }}>
              Fleet<span style={{ color: 'var(--pulse)' }}>Beat</span>
            </div>
            <div style={{ color: 'var(--ink-3)', fontSize: 12, marginTop: 2 }}>
              The live pulse of your fleet
            </div>
          </div>
          <div className="boot-bar">
            <div style={{ width: `${((step + 1) / STEPS.length) * 100}%` }} />
          </div>
          <div style={{ color: 'var(--ink-4)', fontSize: 11.5, fontFamily: 'var(--font-mono)' }}>
            {STEPS[step]}…
          </div>
        </div>
      </div>
    );
  }

  return <App store={ready.store} sim={ready.sim} base={ready.base} />;
}

async function fetchJson(path: string): Promise<unknown> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Could not load ${path} (${res.status}).`);
  return res.json();
}

createRoot(document.getElementById('root')!).render(
  <StrictMode><Boot /></StrictMode>,
);
