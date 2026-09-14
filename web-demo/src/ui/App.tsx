import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActionError } from '../engine/actions';
import { generateRecommendations } from '../engine/intelligence';
import { alertSummary, dispatchExceptions, maintenanceSummary } from '../engine/selectors';
import type { Simulation } from '../engine/sim';
import type { Store } from '../engine/store';
import { AppContext, type AppApi, type Focus } from './app-context';
import { CommandPalette } from './CommandPalette';
import { Avatar, useToasts } from './components/kit';
import {
  IconBell, IconChevron, IconClose, IconMoon, IconPause, IconPlay, IconSearch, IconSun,
} from './icons';
import { NAV, NAV_GROUPS } from './nav';
import type { BaseData } from './map/style';
import { renderModule } from './modules';

export function App({ store, sim, base }: { store: Store; sim: Simulation; base: BaseData }) {
  const [, force] = useState(0);
  const [page, setPage] = useState('live');
  const [params, setParams] = useState<Record<string, string>>({});
  const [collapsed, setCollapsed] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [theme, setThemeState] = useState<'light' | 'dark'>(() => {
    const stored = safeGet('fb-theme');
    if (stored === 'light' || stored === 'dark') return stored;
    // A host may already have stamped its own theme on the root element; respect it
    // before falling back to the operating system preference.
    const stamped = document.documentElement.getAttribute('data-theme');
    if (stamped === 'light' || stamped === 'dark') return stamped;
    return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  });
  const focusRef = useRef<Focus | undefined>(undefined);
  const [, setFocusKey] = useState(0);
  const toasts = useToasts();

  // one subscription drives the whole app
  useEffect(() => store.subscribe(() => force((n) => n + 1)), [store]);

  // the simulation clock
  useEffect(() => {
    let last = performance.now();
    let raf = 0;
    const loop = () => {
      const now = performance.now();
      const dt = Math.min(400, now - last);
      last = now;
      sim.tick(dt);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [sim]);

  // the copilot looks for new recommendations periodically
  useEffect(() => {
    generateRecommendations(store);
    const id = window.setInterval(() => generateRecommendations(store), 45000);
    return () => window.clearInterval(id);
  }, [store]);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    safeSet('fb-theme', theme);
  }, [theme]);

  const navigate = useCallback((next: string, p: Record<string, string> = {}) => {
    setPage(next);
    setParams(p);
    setNotifOpen(false);
  }, []);

  const open = useCallback((kind: string, id: string) => {
    const map: Record<string, [string, string]> = {
      vehicle: ['vehicles', 'vehicle'],
      driver: ['drivers', 'driver'],
      task: ['tasks', 'task'],
      alert: ['alerts', 'alert'],
      trip: ['trips', 'trip'],
      place: ['geofences', 'place'],
      geofence: ['geofences', 'geofence'],
      document: ['compliance', 'document'],
      work_order: ['maintenance', 'workOrder'],
      incident: ['incidents', 'incident'],
    };
    const target = map[kind];
    if (target) navigate(target[0], { [target[1]]: id });
  }, [navigate]);

  const focusMap = useCallback((lat: number, lon: number, zoom?: number) => {
    setFocusKey((k) => {
      focusRef.current = { lat, lon, zoom, key: k + 1 };
      return k + 1;
    });
  }, []);

  const run = useCallback(<T,>(fn: () => T, success?: string): T | undefined => {
    try {
      const result = fn();
      if (success) toasts.push('success', success);
      return result;
    } catch (err) {
      if (err instanceof ActionError) toasts.push('error', err.message, err.hint);
      else toasts.push('error', 'FleetBeat could not complete that action.',
                       'The change was not applied. Try again.');
      return undefined;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      } else if (e.key === 'Escape') {
        setNotifOpen(false);
      } else if (!e.metaKey && !e.ctrlKey && !e.altKey &&
                 !(e.target instanceof HTMLInputElement) &&
                 !(e.target instanceof HTMLTextAreaElement)) {
        const idx = '1234567890'.indexOf(e.key);
        if (idx >= 0 && idx < NAV.length) navigate(NAV[idx].key);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [navigate]);

  const api: AppApi = useMemo(() => ({
    store, state: store.state, theme, setTheme: setThemeState,
    navigate, page, params, open, toast: toasts.push, focusMap, run,
  }), [store, theme, navigate, page, params, open, toasts.push, focusMap, run]);

  const s = store.state;
  const alerts = alertSummary(store);
  const maint = maintenanceSummary(store);
  const exceptions = dispatchExceptions(store);
  const unassigned = s.tasks.filter((t) => t.status === 'unassigned').length;
  const pendingRecs = s.recommendations.filter((r) => r.status === 'pending').length;
  const unread = s.notifications.filter((n) => !n.readAt && n.userId === s.currentUserId);

  const badges: Record<string, { count: number; tone?: string }> = {
    alerts: { count: alerts.critical + alerts.high, tone: alerts.critical ? undefined : 'warn' },
    dispatch: { count: exceptions.filter((e) => e.severity === 'critical' || e.severity === 'high').length, tone: 'warn' },
    tasks: { count: unassigned, tone: 'info' },
    maintenance: { count: maint.overdue + maint.critical, tone: 'warn' },
    ai: { count: pendingRecs, tone: 'info' },
  };

  // The two surfaces below the divider are not customer modules, so they are not in
  // NAV; they still need a heading.
  const OUTSIDE_NAV: Record<string, { label: string; purpose: string }> = {
    'driver-app': { label: 'Driver app', purpose: 'What does the driver see?' },
    platform: { label: 'Platform admin', purpose: 'How is the platform running?' },
  };
  const current = NAV.find((n) => n.key === page) ?? OUTSIDE_NAV[page] ?? NAV[0];

  return (
    <AppContext.Provider value={api}>
      <div className="app">
        <nav className="rail" data-collapsed={collapsed} aria-label="Main">
          <div className="rail-head">
            <span className="logo-mark" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#fff"
                   strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                <path d="M1.5 8h3l1.5-3.5L9 12l1.5-4h4" />
              </svg>
            </span>
            <span className="logo-word">Fleet<span>Beat</span></span>
            <div className="grow" />
            <button className="iconbtn" onClick={() => setCollapsed((v) => !v)}
                    aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
                    title={collapsed ? 'Expand' : 'Collapse'}
                    style={{ transform: collapsed ? 'none' : 'rotate(180deg)' }}>
              <IconChevron size={15} />
            </button>
          </div>

          <div className="rail-nav">
            {NAV_GROUPS.map((group) => {
              const items = NAV.filter((n) => n.group === group);
              if (!items.length) return null;
              return (
                <div key={group}>
                  <div className="rail-group eyebrow">{group}</div>
                  {items.map((item) => {
                    const badge = badges[item.key];
                    const Icon = item.icon;
                    return (
                      <button key={item.key} className="rail-item"
                              aria-current={page === item.key ? 'page' : undefined}
                              onClick={() => navigate(item.key)}
                              title={collapsed ? `${item.label} — ${item.purpose}` : item.purpose}>
                        <Icon size={16} />
                        <span>{item.label}</span>
                        {badge && badge.count > 0 && (
                          <span className="rail-badge" data-tone={badge.tone}>{badge.count}</span>
                        )}
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </div>

          <div className="rail-foot">
            <button className="rail-item" onClick={() => navigate('driver-app')}
                    aria-current={page === 'driver-app' ? 'page' : undefined}
                    title="Open the driver's phone view">
              <IconChevron size={15} />
              <span>Driver app</span>
            </button>
            <button className="rail-item" onClick={() => navigate('platform')}
                    aria-current={page === 'platform' ? 'page' : undefined}
                    title="Internal platform operations console">
              <IconChevron size={15} />
              <span>Platform admin</span>
            </button>
          </div>
        </nav>

        <div className="main">
          <header className="topbar">
            <div className="crumbs">
              <h1>{current.label}</h1>
              <span className="crumb-sep">·</span>
              <span className="muted" style={{ fontSize: 12 }}>{current.purpose}</span>
            </div>
            <div className="grow" />

            <button className="searchbtn" onClick={() => setPaletteOpen(true)}>
              <IconSearch size={14} />
              <span className="grow" style={{ textAlign: 'left', fontSize: 12.5 }}>
                Search the fleet
              </span>
              <span className="kbd">⌘K</span>
            </button>

            <button className="iconbtn" title={s.simRunning ? 'Pause the live feed' : 'Resume the live feed'}
                    data-active={!s.simRunning}
                    onClick={() => { s.simRunning = !s.simRunning; store.emitNow(); }}>
              {s.simRunning ? <IconPause size={15} /> : <IconPlay size={15} />}
            </button>

            <button className="iconbtn" title="Switch theme"
                    onClick={() => setThemeState(theme === 'dark' ? 'light' : 'dark')}>
              {theme === 'dark' ? <IconSun size={16} /> : <IconMoon size={16} />}
            </button>

            <div style={{ position: 'relative' }}>
              <button className="iconbtn" title="Notifications"
                      data-active={notifOpen} onClick={() => setNotifOpen((v) => !v)}>
                <IconBell size={16} />
                {unread.length > 0 && <span className="dot" />}
              </button>
              {notifOpen && (
                <NotificationPanel store={store} onClose={() => setNotifOpen(false)}
                                   onOpen={open} />
              )}
            </div>

            <div className="row" style={{ gap: 8, paddingLeft: 6, borderLeft: '1px solid var(--line)' }}>
              <Avatar name={store.me.fullName} color={store.me.avatarColor} />
              <div style={{ lineHeight: 1.25 }}>
                <div style={{ fontSize: 12, fontWeight: 600 }}>{store.me.fullName}</div>
                <div className="dim" style={{ fontSize: 10.5, textTransform: 'capitalize' }}>
                  {store.me.role.replace('_', ' ')} · {s.org.name}
                </div>
              </div>
            </div>
          </header>

          <div className="content">
            {renderModule(page, base)}
          </div>
        </div>
      </div>

      {paletteOpen && (
        <CommandPalette
          store={store}
          onClose={() => setPaletteOpen(false)}
          onNavigate={navigate}
          onOpen={open}
          onCommand={(key) => {
            if (key === 'toggle-theme') setThemeState(theme === 'dark' ? 'light' : 'dark');
            else if (key === 'toggle-sim') { s.simRunning = !s.simRunning; store.emitNow(); }
            else if (key === 'critical-alerts') navigate('alerts', { view: 'active', severity: 'critical' });
            else if (key === 'create-task') navigate('tasks', { compose: '1' });
            else if (key === 'create-work-order') navigate('maintenance', { compose: '1' });
            else if (key === 'report-incident') navigate('incidents', { compose: '1' });
          }}
        />
      )}
      {toasts.view}
    </AppContext.Provider>
  );
}

function NotificationPanel({ store, onClose, onOpen }: {
  store: Store; onClose: () => void; onOpen: (kind: string, id: string) => void;
}) {
  const s = store.state;
  const mine = s.notifications.filter((n) => n.userId === s.currentUserId).slice(0, 30);
  return (
    <div style={{
      position: 'absolute', top: 40, right: 0, width: 350, zIndex: 40,
      background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 10,
      boxShadow: 'var(--shadow-lift)', maxHeight: 440, display: 'flex',
      flexDirection: 'column',
    }}>
      <div className="card-head">
        <h3>Notifications</h3>
        <div className="grow" />
        <button className="btn" data-size="sm" data-variant="ghost"
                onClick={() => {
                  mine.forEach((n) => { n.readAt = s.now; });
                  store.emitNow();
                }}>
          Mark all read
        </button>
        <button className="iconbtn" onClick={onClose} aria-label="Close"><IconClose size={14} /></button>
      </div>
      <div style={{ overflowY: 'auto' }}>
        {!mine.length && (
          <div style={{ padding: 20, fontSize: 12.5, color: 'var(--ink-3)' }}>
            Nothing yet. Notifications are communication — task assignments, renewals,
            reports. Operational exceptions live in Alerts.
          </div>
        )}
        {mine.map((n) => (
          <button key={n.id} style={{
            display: 'block', width: '100%', textAlign: 'left', padding: '10px 13px',
            borderBottom: '1px solid var(--line-soft)',
            background: n.readAt ? 'transparent' : 'var(--pulse-wash)',
          }} onClick={() => {
            n.readAt = s.now;
            if (n.entityType && n.entityId) onOpen(n.entityType, n.entityId);
            onClose();
          }}>
            <div style={{ fontSize: 12.5, fontWeight: 550 }}>{n.title}</div>
            {n.body && <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>{n.body}</div>}
            <div className="dim mono" style={{ fontSize: 10, marginTop: 3 }}>
              {new Date(n.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function safeGet(k: string): string | null {
  try { return localStorage.getItem(k); } catch { return null; }
}
function safeSet(k: string, v: string) {
  try { localStorage.setItem(k, v); } catch { /* private mode */ }
}
