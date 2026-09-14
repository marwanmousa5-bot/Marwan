// Platform admin — the internal console FleetBeat's own operators use. This is a
// different product surface from the customer app: it reasons about tenants,
// devices, jobs and limits, and it deliberately shows aggregates rather than a
// tenant's operational detail.

import { useMemo, useState } from 'react';
import { useApp, useEpoch } from '../app-context';
import {
  BarChart, Button, Card, Empty, HBar, Kpi, Pill, Tabs, relTime, titleCase,
} from '../components/kit';
import {
  IconBuilding, IconCheck, IconShield, IconTruck, IconRefresh,
} from '../icons';

const DAY = 86400000;

/** The background workers the production deployment runs on Celery. */
const JOBS = [
  { name: 'telemetry.ingest', schedule: 'continuous',
    blurb: 'Consumes device positions, updates vehicle state, opens and closes trips.' },
  { name: 'alerts.evaluate', schedule: 'every 30 s',
    blurb: 'Runs active alert rules against the newest telemetry, with dedupe and cooldown.' },
  { name: 'alerts.escalate', schedule: 'every minute',
    blurb: 'Walks the escalation ladder for alerts nobody has acknowledged.' },
  { name: 'tasks.refresh_sla', schedule: 'every minute',
    blurb: 'Recomputes ETAs and flips tasks to at-risk or breached.' },
  { name: 'maintenance.evaluate', schedule: 'hourly',
    blurb: 'Compares odometers and dates against every active service schedule.' },
  { name: 'compliance.scan', schedule: 'daily 03:00',
    blurb: 'Raises document-expiry alerts at each configured warning threshold.' },
  { name: 'analytics.rollup', schedule: 'daily 02:00',
    blurb: 'Materialises per-day aggregates so reports do not scan raw trips.' },
  { name: 'ai.recommend', schedule: 'every 15 min',
    blurb: 'Regenerates copilot recommendations and anomaly detections.' },
];

export function PlatformAdmin() {
  const app = useApp();
  const epoch = useEpoch();
  const { store, state: s } = app;
  const [tab, setTab] = useState('tenants');

  const stats = useMemo(() => {
    const since = s.now - 30 * DAY;
    return {
      vehicles: s.vehicles.length,
      drivers: s.drivers.length,
      devices: s.devices.length,
      users: s.users.length,
      trips30: s.trips.filter((t) => t.startedAt >= since).length,
      positions: s.trips.reduce((a, t) => a + t.positions.length, 0),
      alerts30: s.alerts.filter((a) => a.triggeredAt >= since).length,
      tasks30: s.tasks.filter((t) => t.createdAt >= since).length,
      auditEntries: s.audit.length,
      storageMb: Math.round(
        (s.trips.length * 0.9 + s.alerts.length * 0.4 + s.audit.length * 0.3) / 100) / 10,
    };
  }, [store, epoch, s.now]);

  // Device health is a platform concern: a silent tracker is a support ticket.
  const devices = useMemo(() => s.devices.map((d) => {
    const vehicle = s.vehicles.find((v) => v.deviceId === d.id);
    const lastSeen = vehicle?.lastPositionAt;
    const ageS = lastSeen ? (s.now - lastSeen) / 1000 : Infinity;
    return {
      device: d, vehicle,
      state: ageS < s.org.settings.gpsLiveThresholdS ? 'reporting'
        : ageS < s.org.settings.gpsStaleThresholdS ? 'delayed'
        : lastSeen ? 'silent' : 'never',
      lastSeen,
    };
  }), [s.devices, s.vehicles, s.now, s.org.settings, epoch]);

  const silent = devices.filter((d) => d.state === 'silent' || d.state === 'never');

  const auditByAction = useMemo(() => {
    const counts: Record<string, number> = {};
    s.audit.forEach((a) => {
      const group = a.action.split('.')[0];
      counts[group] = (counts[group] ?? 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 10);
  }, [epoch, s.audit.length]);

  const dailyLoad = useMemo(() => {
    const buckets: { label: string; value: number }[] = [];
    for (let i = 13; i >= 0; i--) {
      const from = s.now - (i + 1) * DAY;
      const to = s.now - i * DAY;
      buckets.push({
        label: new Date(to).toISOString().slice(5, 10),
        value: s.trips.filter((t) => t.startedAt >= from && t.startedAt < to).length,
      });
    }
    return buckets;
  }, [epoch, s.now]);

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Platform admin</h2>
            <p className="page-sub">
              FleetBeat's own operations console, not the customer's. It sees tenants, device
              health, background jobs and usage — never a tenant's operational detail, because
              tenant data is scoped by organisation at the query layer and platform staff have no
              route around that.
            </p>
          </div>
          <Pill tone="warn"><IconShield size={12} /> Internal surface</Pill>
        </div>

        <div className="banner warn" style={{ marginBottom: 14 }}>
          <IconShield size={16} />
          <div>
            This environment runs a single tenant, <strong>{s.org.name}</strong>, so the tenant
            table below has one row. The figures are that tenant's real usage — nothing on this
            page is a placeholder.
          </div>
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="Tenants" value={1} tone="pulse" />
          <Kpi label="Vehicles" value={stats.vehicles} />
          <Kpi label="Devices" value={stats.devices}
               foot={silent.length ? `${silent.length} not reporting` : 'all reporting'}
               tone={silent.length ? 'warn' : 'good'} />
          <Kpi label="Users" value={stats.users} />
          <Kpi label="Trips, 30 d" value={stats.trips30.toLocaleString()} />
          <Kpi label="Alerts, 30 d" value={stats.alerts30.toLocaleString()} />
          <Kpi label="Audit entries" value={stats.auditEntries.toLocaleString()} />
        </div>

        <Tabs active={tab} onChange={setTab} tabs={[
          { key: 'tenants', label: 'Tenants' },
          { key: 'devices', label: `Devices (${s.devices.length})` },
          { key: 'jobs', label: `Background jobs (${JOBS.length})` },
          { key: 'usage', label: 'Usage' },
          { key: 'isolation', label: 'Tenant isolation' },
        ]} />

        {tab === 'tenants' && (
          <Card title="Tenants" pad={false}>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Organisation</th><th>Tenant id</th><th>Region</th>
                    <th className="num">Vehicles</th><th className="num">Drivers</th>
                    <th className="num">Users</th><th className="num">Trips 30 d</th>
                    <th className="num">Tasks 30 d</th><th>Plan</th><th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>
                      <div className="row-flex">
                        <IconBuilding size={15} />
                        <div>
                          <strong>{s.org.name}</strong>
                          <div className="muted small">{s.org.city}, {s.org.country}</div>
                        </div>
                      </div>
                    </td>
                    <td className="mono small">{s.org.id}</td>
                    <td>eu-north-1</td>
                    <td className="num">{stats.vehicles}</td>
                    <td className="num">{stats.drivers}</td>
                    <td className="num">{stats.users}</td>
                    <td className="num">{stats.trips30.toLocaleString()}</td>
                    <td className="num">{stats.tasks30.toLocaleString()}</td>
                    <td><Pill tone="info">Fleet</Pill></td>
                    <td><Pill tone="good">Active</Pill></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {tab === 'devices' && (
          <>
            {!!silent.length && (
              <div className="banner danger" style={{ marginTop: 14, marginBottom: 14 }}>
                <IconTruck size={16} />
                <div>
                  {silent.length} device{silent.length === 1 ? ' is' : 's are'} not reporting.
                  A silent tracker means the customer is flying blind on that vehicle, which is a
                  platform problem before it is theirs.
                </div>
              </div>
            )}
            <Card title="Device fleet" pad={false}
                  actions={<span className="muted small">
                    Reporting state is derived from the last position, using this tenant's own
                    freshness thresholds
                  </span>}>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Serial</th><th>Model</th><th>Fitted to</th><th>Firmware</th>
                      <th>Last fix</th><th>State</th>
                    </tr>
                  </thead>
                  <tbody>
                    {devices.map((d) => (
                      <tr key={d.device.id}>
                        <td className="mono small">{d.device.serial}</td>
                        <td>{d.device.model}</td>
                        <td>
                          {d.vehicle
                            ? <>{d.vehicle.name} <span className="muted">· {d.vehicle.plate}</span></>
                            : <span className="muted">Unassigned</span>}
                        </td>
                        <td className="mono small">{d.device.firmware ?? '—'}</td>
                        <td>{d.lastSeen ? relTime(d.lastSeen, s.now) : 'never'}</td>
                        <td>
                          <Pill tone={d.state === 'reporting' ? 'good'
                            : d.state === 'delayed' ? 'warn' : 'danger'}>
                            {titleCase(d.state)}
                          </Pill>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card title="Why customers cannot reassign devices">
              <p className="muted" style={{ marginTop: 0 }}>
                A GPS unit is platform hardware with an identity of its own. Letting a customer
                point a device at a different vehicle would let them rewrite whose history the
                positions belong to, which breaks both the audit trail and any dispute about a
                delivery. Fitting and refitting is a platform operation, recorded here.
              </p>
            </Card>
          </>
        )}

        {tab === 'jobs' && (
          <Card title="Background workers" pad={false}
                actions={<span className="muted small">
                  Celery workers in the production deployment; the same logic runs in-process here
                </span>}>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr><th>Job</th><th>Schedule</th><th>What it does</th><th>State</th></tr>
                </thead>
                <tbody>
                  {JOBS.map((j) => (
                    <tr key={j.name}>
                      <td className="mono small">{j.name}</td>
                      <td>{j.schedule}</td>
                      <td className="muted">{j.blurb}</td>
                      <td>
                        <Pill tone={s.simRunning ? 'good' : 'warn'}>
                          {s.simRunning ? 'Running' : 'Paused'}
                        </Pill>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {tab === 'usage' && (
          <div className="grid-2" style={{ marginTop: 14 }}>
            <Card title="Trips ingested per day (14 days)">
              <BarChart data={dailyLoad} format={(v) => `${v} trips`} />
              <p className="muted small" style={{ marginTop: 10 }}>
                Load is what drives cost: each trip carries its samples, and the analytics rollup
                exists so that reporting never scans them directly.
              </p>
            </Card>
            <Card title="Stored records">
              <HBar label="Trips" value={s.trips.length} max={Math.max(s.trips.length, 1)} />
              <HBar label="Position samples" value={stats.positions}
                    max={Math.max(stats.positions, 1)} tone="var(--good)" />
              <HBar label="Alerts" value={s.alerts.length}
                    max={Math.max(s.trips.length, 1)} tone="var(--warn)" />
              <HBar label="Driver events" value={s.driverEvents.length}
                    max={Math.max(s.trips.length, 1)} tone="var(--warn)" />
              <HBar label="Audit entries" value={s.audit.length}
                    max={Math.max(s.trips.length, 1)} tone="var(--bad)" />
              <p className="muted small" style={{ marginTop: 10 }}>
                Approximately {stats.storageMb.toFixed(1)} MB for this tenant at current retention.
              </p>
            </Card>
            <Card title="Write activity by area">
              {auditByAction.length
                ? auditByAction.map(([group, n]) => (
                    <HBar key={group} label={titleCase(group)} value={n}
                          max={auditByAction[0][1]} />
                  ))
                : <Empty title="No audit activity yet"
                         body="Entries appear as soon as anyone changes something." />}
            </Card>
            <Card title="Runtime">
              <dl className="dl">
                <dt>Clock</dt><dd>{new Date(s.now).toLocaleString()}</dd>
                <dt>Feed</dt>
                <dd><Pill tone={s.connection === 'live' ? 'good' : 'warn'}>
                  {titleCase(s.connection)}
                </Pill></dd>
                <dt>Ticks</dt><dd className="num">{s.ticks.toLocaleString()}</dd>
                <dt>Last event</dt><dd>{relTime(s.lastEventAt, s.now)}</dd>
                <dt>Routing</dt><dd>Built-in A* · {store.graph.nodes.length.toLocaleString()} nodes</dd>
              </dl>
              <Button onClick={() => app.run(() => { store.emitNow(); }, 'State refreshed')}>
                <IconRefresh size={13} /> Refresh
              </Button>
            </Card>
          </div>
        )}

        {tab === 'isolation' && (
          <div className="grid-2" style={{ marginTop: 14 }}>
            <Card title="How tenant isolation is enforced">
              <ul className="tight">
                <li>Every tenant-scoped table carries <code>organization_id</code>, indexed and
                    non-null.</li>
                <li>The organisation is resolved from the authenticated token, never from a request
                    body, query string or header the client controls.</li>
                <li>Repository queries are constructed with the tenant filter applied at the session
                    level, so a query that forgets it returns nothing rather than someone else's
                    rows.</li>
                <li>Cross-tenant identifiers fail as <em>not found</em>, not as <em>forbidden</em>,
                    so probing cannot confirm that another tenant's record exists.</li>
                <li>Platform staff see aggregates. Reading a tenant's operational records requires
                    that tenant's own grant, and the access is itself audited.</li>
              </ul>
            </Card>
            <Card title="What the audit log guarantees">
              <ul className="tight">
                <li>Append-only: entries are never updated or deleted, including by platform staff.</li>
                <li>Each entry stores the actor, their role, the entity, and the before and after
                    values of what changed.</li>
                <li>Every AI-applied action is recorded as an ordinary audited action with the
                    person who confirmed it named as the actor.</li>
                <li>Authentication events — sign-in, refresh, role change, identity switch — are
                    audited alongside operational changes.</li>
              </ul>
              <Button onClick={() => app.navigate('settings', { tab: 'audit' })}>
                <IconCheck size={13} /> Open this tenant's audit log
              </Button>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}
