import { createContext, useContext, useEffect, useRef, useState } from 'react';
import type { Store, State } from '../engine/store';

export interface Focus { lat: number; lon: number; zoom?: number; key: number }

export interface AppApi {
  store: Store;
  state: State;
  theme: 'light' | 'dark';
  setTheme: (t: 'light' | 'dark') => void;
  navigate: (page: string, params?: Record<string, string>) => void;
  page: string;
  params: Record<string, string>;
  open: (kind: string, id: string) => void;
  toast: (tone: 'success' | 'error' | 'info', text: string, hint?: string) => void;
  focusMap: (lat: number, lon: number, zoom?: number) => void;
  run: <T>(fn: () => T, success?: string) => T | undefined;
}

export const AppContext = createContext<AppApi | null>(null);

export function useApp(): AppApi {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used inside the FleetBeat shell');
  return ctx;
}

/**
 * Heavy read models (analytics, costs, sustainability, the leaderboard) scan tens
 * of thousands of records. State is mutated in place, so a `useMemo` keyed on the
 * arrays themselves would never recompute — and one keyed on every store emit would
 * recompute on every animation frame. This returns a counter that advances at most
 * once per `ms`, and only when the store has actually changed since the last advance.
 */
export function useEpoch(ms = 1000): number {
  const { store } = useApp();
  const [epoch, setEpoch] = useState(0);
  const seen = useRef(-1);
  useEffect(() => {
    const check = () => {
      if (store.revision !== seen.current) {
        seen.current = store.revision;
        setEpoch((n) => n + 1);
      }
    };
    check();
    const id = window.setInterval(check, ms);
    return () => window.clearInterval(id);
  }, [store, ms]);
  return epoch;
}
