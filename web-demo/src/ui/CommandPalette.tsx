// ⌘K / Ctrl+K. Searches vehicles, drivers, tasks, trips, alerts, places,
// geofences and documents, and runs the commands the current role may run.

import { useEffect, useMemo, useRef, useState } from 'react';
import { NAV } from './nav';
import type { Store } from '../engine/store';

export interface PaletteResult {
  id: string;
  group: string;
  title: string;
  sub?: string;
  tag?: string;
  run: () => void;
}

export function CommandPalette({ store, onClose, onNavigate, onOpen, onCommand }: {
  store: Store;
  onClose: () => void;
  onNavigate: (key: string) => void;
  onOpen: (kind: string, id: string) => void;
  onCommand: (key: string) => void;
}) {
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const results = useMemo(() => search(store, q, { onNavigate, onOpen, onCommand, onClose }),
                          [store, q, onNavigate, onOpen, onCommand, onClose]);

  useEffect(() => { setActive(0); }, [q]);

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>('[data-active="true"]');
    el?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); results[active]?.run(); }
    else if (e.key === 'Escape') onClose();
  };

  let lastGroup = '';
  return (
    <div className="palette-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command palette">
        <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)}
               onKeyDown={onKey} placeholder="Search vehicles, drivers, tasks, places — or type a command"
               aria-label="Search FleetBeat" />
        <div className="palette-list" ref={listRef}>
          {results.length === 0 && (
            <div style={{ padding: '18px 14px', color: 'var(--ink-3)', fontSize: 12.5 }}>
              Nothing matches “{q}”. Try a plate, a driver name, a task reference like TSK-1042,
              or a command such as “create task”.
            </div>
          )}
          {results.map((r, i) => {
            const head = r.group !== lastGroup ? (lastGroup = r.group) : null;
            return (
              <div key={r.id}>
                {head && <div className="palette-group">{head}</div>}
                <button className="palette-item" data-active={i === active}
                        onMouseEnter={() => setActive(i)} onClick={r.run}>
                  <span className="grow">
                    <span className="title">{r.title}</span>
                    {r.sub && <div className="sub">{r.sub}</div>}
                  </span>
                  {r.tag && <span className="tag">{r.tag}</span>}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function search(
  store: Store, raw: string,
  handlers: {
    onNavigate: (k: string) => void; onOpen: (kind: string, id: string) => void;
    onCommand: (k: string) => void; onClose: () => void;
  },
): PaletteResult[] {
  const s = store.state;
  const q = raw.trim().toLowerCase();
  const out: PaletteResult[] = [];
  const go = (fn: () => void) => () => { fn(); handlers.onClose(); };
  const match = (...fields: (string | undefined)[]) =>
    !q || fields.some((f) => f?.toLowerCase().includes(q));

  // commands first when the query looks like a verb
  const commands = [
    { key: 'create-task', title: 'Create task', sub: 'Guided task workflow', tag: 'Command' },
    { key: 'create-work-order', title: 'Create maintenance work order', sub: 'Raise workshop work', tag: 'Command' },
    { key: 'report-incident', title: 'Report incident', sub: 'Log a collision, breakdown or near miss', tag: 'Command' },
    { key: 'critical-alerts', title: 'View critical alerts', sub: 'Alert centre, filtered to critical', tag: 'Command' },
    { key: 'toggle-theme', title: 'Toggle light / dark theme', tag: 'Command' },
    { key: 'toggle-sim', title: 'Pause or resume the live feed', tag: 'Command' },
  ];
  commands.filter((c) => match(c.title, c.sub)).forEach((c) => out.push({
    id: `cmd:${c.key}`, group: 'Commands', title: c.title, sub: c.sub, tag: c.tag,
    run: go(() => handlers.onCommand(c.key)),
  }));

  NAV.filter((n) => match(n.label, n.purpose)).forEach((n) => out.push({
    id: `nav:${n.key}`, group: 'Go to', title: n.label, sub: n.purpose, tag: 'Page',
    run: go(() => handlers.onNavigate(n.key)),
  }));

  if (q.length >= 1) {
    s.vehicles.filter((v) => match(v.name, v.plate, v.make, v.model, v.street))
      .slice(0, 6).forEach((v) => {
        const driver = store.driver(v.driverId);
        out.push({
          id: `vh:${v.id}`, group: 'Vehicles', title: `${v.name} · ${v.plate}`,
          sub: [v.make && `${v.make} ${v.model}`, driver?.fullName, v.street]
            .filter(Boolean).join(' · '),
          tag: 'Vehicle', run: go(() => handlers.onOpen('vehicle', v.id)),
        });
      });

    s.drivers.filter((d) => match(d.fullName, d.employeeNo, d.phone))
      .slice(0, 5).forEach((d) => {
        const v = s.vehicles.find((x) => x.driverId === d.id);
        out.push({
          id: `dr:${d.id}`, group: 'Drivers', title: d.fullName,
          sub: [d.employeeNo, v && `Driving ${v.name}`, `Safety ${d.safetyScore.toFixed(0)}`]
            .filter(Boolean).join(' · '),
          tag: 'Driver', run: go(() => handlers.onOpen('driver', d.id)),
        });
      });

    s.tasks.filter((t) => match(t.reference, t.title, t.address))
      .slice(0, 6).forEach((t) => out.push({
        id: `tk:${t.id}`, group: 'Tasks', title: `${t.reference} — ${t.title}`,
        sub: `${t.status.replace('_', ' ')} · ${t.address}`,
        tag: 'Task', run: go(() => handlers.onOpen('task', t.id)),
      }));

    s.alerts.filter((a) => match(a.title, a.code, a.street))
      .slice(0, 5).forEach((a) => out.push({
        id: `al:${a.id}`, group: 'Alerts', title: a.title,
        sub: `${a.severity} · ${a.status}`,
        tag: 'Alert', run: go(() => handlers.onOpen('alert', a.id)),
      }));

    s.trips.filter((t) => match(t.reference, t.startAddress, t.endAddress))
      .slice(0, 4).forEach((t) => out.push({
        id: `tr:${t.id}`, group: 'Trips', title: t.reference,
        sub: `${t.startAddress} → ${t.endAddress ?? 'in progress'} · ${t.distanceKm.toFixed(1)} km`,
        tag: 'Trip', run: go(() => handlers.onOpen('trip', t.id)),
      }));

    s.places.filter((p) => match(p.name, p.address))
      .slice(0, 5).forEach((p) => out.push({
        id: `pl:${p.id}`, group: 'Places', title: p.name,
        sub: `${p.category.replace('_', ' ')} · ${p.address ?? ''}`,
        tag: 'Place', run: go(() => handlers.onOpen('place', p.id)),
      }));

    s.geofences.filter((g) => match(g.name)).slice(0, 4).forEach((g) => out.push({
      id: `gf:${g.id}`, group: 'Geofences', title: g.name,
      sub: `${g.kind} · trigger on ${g.trigger}`,
      tag: 'Geofence', run: go(() => handlers.onOpen('geofence', g.id)),
    }));

    s.documents.filter((d) => match(d.name, d.reference, d.issuer))
      .slice(0, 4).forEach((d) => out.push({
        id: `doc:${d.id}`, group: 'Documents', title: d.name,
        sub: `${d.kind.replace('_', ' ')} · expires ${d.expiryDate}`,
        tag: 'Document', run: go(() => handlers.onOpen('document', d.id)),
      }));

    s.workOrders.filter((w) => match(w.reference, w.title))
      .slice(0, 4).forEach((w) => out.push({
        id: `wo:${w.id}`, group: 'Work orders', title: `${w.reference} — ${w.title}`,
        sub: w.status.replace(/_/g, ' '),
        tag: 'Work order', run: go(() => handlers.onOpen('work_order', w.id)),
      }));
  }

  return out.slice(0, 40);
}
