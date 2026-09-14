// Shared UI primitives. Every status reads as colour + shape + words, so the
// interface never depends on colour alone.

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { IconCheck, IconClose } from '../icons';

export type Tone =
  | 'neutral' | 'info' | 'good' | 'warn' | 'danger'
  | 'critical' | 'high' | 'medium' | 'low'
  | 'moving' | 'idle' | 'stopped' | 'offline' | 'maintenance' | 'not_tracked';

export function Pill({ tone = 'neutral', children, title }: {
  tone?: Tone; children: ReactNode; title?: string;
}) {
  return (
    <span className="pill" data-tone={tone} title={title}>
      <i className="glyph" /> {children}
    </span>
  );
}

export function Button({
  children, variant, size, onClick, disabled, title, type = 'button', style,
}: {
  children: ReactNode;
  variant?: 'primary' | 'danger' | 'ghost';
  size?: 'sm' | 'lg';
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
  type?: 'button' | 'submit';
  style?: React.CSSProperties;
}) {
  return (
    <button className="btn" data-variant={variant} data-size={size} onClick={onClick}
            disabled={disabled} title={title} type={type} style={style}>
      {children}
    </button>
  );
}

export function Field({ label, hint, children }: {
  label: string; hint?: string; children: ReactNode;
}) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

export function Card({ title, actions, children, pad = true, footer }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; pad?: boolean;
  footer?: ReactNode;
}) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-head">
          {typeof title === 'string' ? <h3>{title}</h3> : title}
          <div className="grow" />
          {actions}
        </header>
      )}
      <div className={pad ? 'card-pad' : ''}>{children}</div>
      {footer}
    </section>
  );
}

export function Kpi({ label, value, unit, foot, tone, onClick, active }: {
  label: string; value: ReactNode; unit?: string; foot?: ReactNode;
  tone?: 'danger' | 'warn' | 'good' | 'pulse'; onClick?: () => void; active?: boolean;
}) {
  const inner = (
    <>
      <span className="label">{label}</span>
      <span className="value">{value}{unit && <span className="unit">{unit}</span>}</span>
      {foot && <span className="foot">{foot}</span>}
    </>
  );
  return onClick
    ? <button className="kpi" data-tone={tone} data-on={active} onClick={onClick}>{inner}</button>
    : <div className="kpi" data-tone={tone}>{inner}</div>;
}

export function Empty({ title, body, action }: {
  title: string; body: string; action?: ReactNode;
}) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      <p>{body}</p>
      {action}
    </div>
  );
}

export function Modal({ title, subtitle, onClose, children, footer, size }: {
  title: string; subtitle?: ReactNode; onClose: () => void; children: ReactNode;
  footer?: ReactNode; size?: 'lg' | 'xl';
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="modal-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" data-size={size} role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal-head">
          <div className="grow">
            <h2>{title}</h2>
            {subtitle && <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>{subtitle}</div>}
          </div>
          <button className="iconbtn" onClick={onClose} aria-label="Close"><IconClose /></button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>
  );
}

export function Confirm({ title, body, consequences, confirmLabel, tone, onConfirm, onCancel, busy }: {
  title: string; body: ReactNode; consequences?: ReactNode; confirmLabel: string;
  tone?: 'danger' | 'primary'; onConfirm: () => void; onCancel: () => void; busy?: boolean;
}) {
  return (
    <Modal title={title} onClose={onCancel} footer={
      <>
        <Button onClick={onCancel}>Cancel</Button>
        <Button variant={tone ?? 'primary'} onClick={onConfirm} disabled={busy}>
          {confirmLabel}
        </Button>
      </>
    }>
      <div className="stack">
        <div>{body}</div>
        {consequences}
      </div>
    </Modal>
  );
}

export function Tabs({ tabs, active, onChange }: {
  tabs: { key: string; label: string; count?: number }[];
  active: string; onChange: (k: string) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.key} className="tab" role="tab" aria-selected={active === t.key}
                onClick={() => onChange(t.key)}>
          {t.label}
          {t.count != null && <span className="mono muted" style={{ marginLeft: 6, fontSize: 11 }}>{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Progress({ pct, tone }: { pct: number; tone?: 'warn' | 'danger' | 'good' }) {
  return (
    <div className="progress" data-tone={tone}
         role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <div style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
    </div>
  );
}

export function Switch({ on, onChange, label }: {
  on: boolean; onChange: (v: boolean) => void; label: string;
}) {
  return (
    <button className="layer-row" onClick={() => onChange(!on)} role="switch" aria-checked={on}>
      <span className="switch" data-on={on} />
      <span>{label}</span>
    </button>
  );
}

export function Avatar({ name, color, size = 26 }: { name: string; color: string; size?: number }) {
  const initials = name.split(' ').map((p) => p[0]).slice(0, 2).join('').toUpperCase();
  return (
    <span className="avatar" style={{ background: color, width: size, height: size,
                                      fontSize: Math.round(size * 0.4) }} title={name}>
      {initials}
    </span>
  );
}

export function HBar({ label, value, max, format, tone }: {
  label: string; value: number; max: number; format?: (v: number) => string; tone?: string;
}) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="hbar">
      <span className="truncate" title={label}>{label}</span>
      <span className="track"><span className="fill" style={{
        width: `${Math.max(1, pct)}%`,
        background: tone ?? 'var(--pulse)',
      }} /></span>
      <span className="val">{format ? format(value) : value.toLocaleString()}</span>
    </div>
  );
}

/** Compact trend line. Labels stay outside so nothing clips. */
export function Sparkline({ points, height = 38, tone = 'var(--pulse)', fill = true }: {
  points: number[]; height?: number; tone?: string; fill?: boolean;
}) {
  if (points.length < 2) return <div className="spark" style={{ height }} />;
  const w = 240;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const pad = 3;
  const coords = points.map((p, i) => {
    const x = (i / (points.length - 1)) * (w - pad * 2) + pad;
    const y = height - pad - ((p - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });
  const d = coords.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const area = `${d} L${coords[coords.length - 1][0].toFixed(1)},${height} L${coords[0][0].toFixed(1)},${height} Z`;
  const last = coords[coords.length - 1];
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none"
         style={{ height }} aria-hidden="true">
      {fill && <path d={area} fill={tone} opacity={0.12} />}
      <path d={d} fill="none" stroke={tone} strokeWidth={1.6} strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r={2.6} fill={tone} />
    </svg>
  );
}

/** Column chart with a real scale; every label names a value the chart reaches. */
export function BarChart({ data, height = 150, format, tone = 'var(--pulse)' }: {
  data: { label: string; value: number }[]; height?: number;
  format?: (v: number) => string; tone?: string;
}) {
  if (!data.length) return null;
  const max = Math.max(...data.map((d) => d.value), 1);
  const ticks = [0, max / 2, max];
  return (
    <div>
      <div style={{ display: 'flex', gap: 8 }}>
        <div style={{
          display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
          height, fontSize: 10, color: 'var(--ink-4)', fontFamily: 'var(--font-mono)',
          textAlign: 'right', minWidth: 34,
        }}>
          {[...ticks].reverse().map((t, i) => (
            <span key={i}>{format ? format(t) : Math.round(t).toLocaleString()}</span>
          ))}
        </div>
        <div style={{
          flex: 1, height, display: 'flex', alignItems: 'flex-end', gap: 3,
          borderLeft: '1px solid var(--line)', borderBottom: '1px solid var(--line)',
          paddingLeft: 4, position: 'relative',
        }}>
          {[0.5].map((f) => (
            <span key={f} style={{
              position: 'absolute', left: 0, right: 0, bottom: `${f * 100}%`,
              borderTop: '1px dashed var(--line-soft)',
            }} />
          ))}
          {data.map((d, i) => (
            <div key={i} title={`${d.label}: ${format ? format(d.value) : d.value}`}
                 style={{
                   flex: 1, minWidth: 2,
                   height: `${Math.max(1, (d.value / max) * 100)}%`,
                   background: tone, borderRadius: '2px 2px 0 0', opacity: 0.88,
                 }} />
          ))}
        </div>
      </div>
      <div style={{
        display: 'flex', justifyContent: 'space-between', fontSize: 10,
        color: 'var(--ink-4)', marginTop: 4, paddingLeft: 42,
        fontFamily: 'var(--font-mono)',
      }}>
        <span>{data[0].label}</span>
        <span>{data[data.length - 1].label}</span>
      </div>
    </div>
  );
}

export function Donut({ segments, size = 120, centerLabel, centerValue }: {
  segments: { label: string; value: number; color: string }[];
  size?: number; centerLabel?: string; centerValue?: string;
}) {
  const total = segments.reduce((a, s) => a + s.value, 0) || 1;
  const r = size / 2 - 12;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
          {segments.map((s, i) => {
            const len = (s.value / total) * c;
            const el = (
              <circle key={i} cx={size / 2} cy={size / 2} r={r} fill="none"
                      stroke={s.color} strokeWidth={13}
                      strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset} />
            );
            offset += len;
            return el;
          })}
        </g>
        {centerValue && (
          <text x="50%" y="48%" textAnchor="middle" fill="var(--ink)"
                style={{ fontSize: 19, fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
            {centerValue}
          </text>
        )}
        {centerLabel && (
          <text x="50%" y="62%" textAnchor="middle" fill="var(--ink-4)" style={{ fontSize: 9.5 }}>
            {centerLabel}
          </text>
        )}
      </svg>
      <div className="stack-sm" style={{ fontSize: 12 }}>
        {segments.filter((s) => s.value > 0).map((s, i) => (
          <div key={i} className="row" style={{ gap: 7 }}>
            <i style={{ width: 9, height: 9, borderRadius: 2, background: s.color }} />
            <span className="grow truncate">{s.label}</span>
            <span className="mono muted">{Math.round((s.value / total) * 100)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Timeline({ entries }: {
  entries: { id: string; occurredAt: number; actorType: string; actorName: string;
             description: string }[];
}) {
  if (!entries.length) {
    return <div className="muted" style={{ fontSize: 12 }}>Nothing recorded yet.</div>;
  }
  return (
    <div className="timeline">
      {entries.map((e) => (
        <div className="tl-item" key={e.id} data-actor={e.actorType}>
          <span className="tl-time">
            {new Date(e.occurredAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
          <span className="tl-rail"><span className="tl-dot" /></span>
          <span className="tl-body">
            {e.description}
            <div className="who">
              {e.actorName} · {new Date(e.occurredAt).toLocaleDateString([], { day: '2-digit', month: 'short' })}
            </div>
          </span>
        </div>
      ))}
    </div>
  );
}

export function useToasts() {
  const [toasts, setToasts] = useState<{ id: number; tone: string; text: string; hint?: string }[]>([]);
  const seq = useRef(0);
  const push = (tone: 'success' | 'error' | 'info', text: string, hint?: string) => {
    const id = ++seq.current;
    setToasts((t) => [...t, { id, tone, text, hint }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === 'error' ? 6500 : 4200);
  };
  const view = (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div className="toast" key={t.id} data-tone={t.tone}>
          {t.tone === 'success' && <IconCheck size={15} />}
          <span className="body">
            {t.text}
            {t.hint && <div className="hint">{t.hint}</div>}
          </span>
        </div>
      ))}
    </div>
  );
  return { push, view };
}

export function Money({ value, currency = 'EUR' }: { value: number; currency?: string }) {
  return (
    <span className="num">
      {new Intl.NumberFormat(undefined, {
        style: 'currency', currency, maximumFractionDigits: 0,
      }).format(value)}
    </span>
  );
}

export function relTime(ts: number, now: number): string {
  const s = Math.max(0, Math.round((now - ts) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function hm(ts?: number): string {
  if (!ts) return '—';
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function dmy(ts?: number | string): string {
  if (!ts) return '—';
  const d = typeof ts === 'string' ? new Date(ts + 'T00:00:00Z') : new Date(ts);
  return d.toLocaleDateString([], { day: '2-digit', month: 'short', year: 'numeric' });
}

export function titleCase(s: string): string {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
