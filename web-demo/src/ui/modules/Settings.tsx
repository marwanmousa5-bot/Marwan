// Settings — the numbers the rest of FleetBeat is calculated from.
//
// Nothing on this page is decorative. Change the diesel emission factor and the
// Sustainability page moves; change a safety weight and every driver is re-scored
// on save; change the GPS thresholds and Live Tracking reclassifies vehicles.

import { useState } from 'react';
import {
  setAlertRuleActive, setUserRole, switchUser, updateOrgProfile, updateSettings,
} from '../../engine/actions';
import { useApp } from '../app-context';
import {
  Avatar, Button, Card, Confirm, Empty, Field, Kpi, Pill, Switch, Tabs,
  relTime, titleCase,
} from '../components/kit';
import { IconCheck, IconRefresh, IconShield } from '../icons';

const ROLES: { value: string; label: string; blurb: string }[] = [
  { value: 'org_admin', label: 'Administrator',
    blurb: 'Everything, including settings, users, roles and vehicle retirement.' },
  { value: 'dispatcher', label: 'Dispatcher',
    blurb: 'Operate the fleet: tasks, routes, alerts, maintenance. No settings or users.' },
  { value: 'driver', label: 'Driver',
    blurb: 'Only their own tasks and vehicle, through the driver app.' },
];

function NumberSetting({ label, hint, value, step, suffix, onSave }: {
  label: string; hint?: string; value: number; step?: number; suffix?: string;
  onSave: (v: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  const dirty = draft !== String(value) && draft.trim() !== '' && !Number.isNaN(Number(draft));
  return (
    <Field label={label} hint={hint}>
      <div className="row-flex">
        <input className="input num" type="number" step={step ?? 0.01} value={draft}
               onChange={(e) => setDraft(e.target.value)} style={{ maxWidth: 150 }} />
        {suffix && <span className="muted small">{suffix}</span>}
        <div className="grow" />
        {dirty && (
          <>
            <Button size="sm" onClick={() => setDraft(String(value))}>Revert</Button>
            <Button size="sm" variant="primary" onClick={() => onSave(Number(draft))}>
              <IconCheck size={13} /> Save
            </Button>
          </>
        )}
      </div>
    </Field>
  );
}

export function Settings() {
  const app = useApp();
  const { store, state: s } = app;
  const cfg = s.org.settings;
  const [tab, setTab] = useState('organisation');
  const [orgName, setOrgName] = useState(s.org.name);
  const [roleChange, setRoleChange] = useState<{ userId: string; role: string } | null>(null);
  const me = store.me;
  const isAdmin = me.role === 'org_admin' || me.role === 'super_admin';

  const save = (changes: Parameters<typeof updateSettings>[1], label: string) =>
    app.run(() => updateSettings(store, changes, label), `${label} saved`);

  const target = roleChange ? store.user(roleChange.userId) : null;

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Settings</h2>
            <p className="page-sub">
              These values are inputs to live calculations, not preferences. Every change is
              written to the audit log with the previous value beside the new one.
            </p>
          </div>
          <Pill tone={isAdmin ? 'good' : 'warn'}>
            <IconShield size={12} /> Signed in as {titleCase(me.role)}
          </Pill>
        </div>

        {!isAdmin && (
          <div className="banner warn" style={{ marginBottom: 14 }}>
            <IconShield size={16} />
            <div>
              You are acting as a <strong>{titleCase(me.role)}</strong>. Settings are read-only for
              this role — the controls below are disabled by the same rule the API would enforce,
              not merely hidden. Switch to an administrator under <em>Users</em> to edit.
            </div>
          </div>
        )}

        <Tabs active={tab} onChange={setTab} tabs={[
          { key: 'organisation', label: 'Organisation' },
          { key: 'users', label: `Users (${s.users.length})` },
          { key: 'operations', label: 'Operations' },
          { key: 'safety', label: 'Safety & rewards' },
          { key: 'emissions', label: 'Fuel & emissions' },
          { key: 'rules', label: `Alert rules (${s.alertRules.length})` },
          { key: 'audit', label: `Audit log (${s.audit.length})` },
        ]} />

        {tab === 'organisation' && (
          <div className="grid-2" style={{ marginTop: 14 }}>
            <Card title="Organisation profile">
              <Field label="Name" hint="Shown in the header, on reports and on driver notifications.">
                <div className="row-flex">
                  <input className="input" value={orgName} disabled={!isAdmin}
                         onChange={(e) => setOrgName(e.target.value)} />
                  {orgName !== s.org.name && orgName.trim() && (
                    <Button size="sm" variant="primary" onClick={() => app.run(
                      () => updateOrgProfile(store, { name: orgName.trim() }),
                      'Organisation renamed')}>Save</Button>
                  )}
                </div>
              </Field>
              <dl className="dl">
                <dt>Operating city</dt><dd>{s.org.city}, {s.org.country}</dd>
                <dt>Currency</dt><dd>{cfg.currency}</dd>
                <dt>Vehicles</dt><dd className="num">{s.vehicles.length}</dd>
                <dt>Drivers</dt><dd className="num">{s.drivers.length}</dd>
                <dt>Tenant id</dt><dd className="mono">{s.org.id}</dd>
              </dl>
            </Card>

            <Card title="Appearance">
              <Field label="Theme"
                     hint="Dark is tuned for control rooms: lower luminance so vehicle colours and
                           alert states carry the attention instead of the chrome.">
                <div className="seg">
                  <button className={`seg-btn ${app.theme === 'light' ? 'on' : ''}`}
                          onClick={() => app.setTheme('light')}>Light</button>
                  <button className={`seg-btn ${app.theme === 'dark' ? 'on' : ''}`}
                          onClick={() => app.setTheme('dark')}>Dark</button>
                </div>
              </Field>
              <Field label="Saved views"
                     hint="Map filter combinations saved from Live Tracking.">
                {s.savedViews.length
                  ? <ul className="tight">
                      {s.savedViews.map((v) => <li key={v.id}>{v.name}</li>)}
                    </ul>
                  : <p className="muted small">None saved yet.</p>}
              </Field>
            </Card>

            <Card title="Data provenance">
              <p className="muted" style={{ marginTop: 0 }}>
                The map, the street names, the routing graph and the customer sites in this
                environment all come from an OpenStreetMap extract of Helsinki. Routing is an A*
                search over the real street graph, and every trip you can replay was driven along
                actual roads. No geometry is fabricated.
              </p>
              <dl className="dl">
                <dt>Basemap</dt><dd>OpenStreetMap contributors (ODbL)</dd>
                <dt>Routing</dt><dd>Built-in A* over the extracted graph</dd>
                <dt>Places</dt><dd>Real named POIs from the same extract</dd>
              </dl>
            </Card>

            <Card title="Simulation">
              <dl className="dl">
                <dt>Clock</dt><dd>{new Date(s.now).toLocaleString()}</dd>
                <dt>State</dt>
                <dd><Pill tone={s.simRunning ? 'good' : 'warn'}>
                  {s.simRunning ? 'Running' : 'Paused'}
                </Pill></dd>
                <dt>Speed</dt><dd className="num">{s.simSpeed}×</dd>
                <dt>Ticks processed</dt><dd className="num">{s.ticks.toLocaleString()}</dd>
                <dt>Trips recorded</dt><dd className="num">{s.trips.length.toLocaleString()}</dd>
              </dl>
              <p className="muted small">
                Telemetry is generated locally so the fleet keeps moving without a vehicle gateway.
                Everything downstream of it — trips, alerts, geofence crossings, scores — is the
                same code path a real device feed would drive.
              </p>
            </Card>
          </div>
        )}

        {tab === 'users' && (
          <>
            <Card title="Users and roles" pad={false}
                  actions={<span className="muted small">
                    Role is enforced in the action layer, not by hiding buttons
                  </span>}>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>User</th><th>Email</th><th>Role</th><th>Linked driver</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.users.map((u) => (
                      <tr key={u.id} className={u.id === me.id ? 'is-me' : ''}>
                        <td>
                          <div className="row-flex">
                            <Avatar name={u.fullName} color={u.avatarColor} />
                            <div>
                              <strong>{u.fullName}</strong>
                              {u.id === me.id && <span className="muted small"> · you</span>}
                            </div>
                          </div>
                        </td>
                        <td className="muted">{u.email}</td>
                        <td>
                          <select className="select" value={u.role} disabled={!isAdmin}
                                  onChange={(e) => setRoleChange({
                                    userId: u.id, role: e.target.value,
                                  })}>
                            {ROLES.map((r) => (
                              <option key={r.value} value={r.value}>{r.label}</option>
                            ))}
                            {u.role === 'super_admin' &&
                              <option value="super_admin">Platform super admin</option>}
                          </select>
                        </td>
                        <td>{u.driverId ? store.driver(u.driverId)?.fullName ?? '—' : '—'}</td>
                        <td>
                          {u.id !== me.id && (
                            <Button size="sm" onClick={() => app.run(
                              () => switchUser(store, u.id),
                              `Now acting as ${u.fullName}`)}>
                              Act as
                            </Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            <div className="card-grid" style={{ marginTop: 14 }}>
              {ROLES.map((r) => (
                <Card key={r.value} title={r.label}>
                  <p className="muted" style={{ marginTop: 0 }}>{r.blurb}</p>
                  <Pill tone="neutral">
                    {s.users.filter((u) => u.role === r.value).length} user(s)
                  </Pill>
                </Card>
              ))}
            </div>
          </>
        )}

        {tab === 'operations' && (
          <div className="grid-2" style={{ marginTop: 14 }}>
            <Card title="GPS freshness">
              <p className="muted small" style={{ marginTop: 0 }}>
                A vehicle is only called live while its last fix is recent. These thresholds decide
                the LIVE / STALE / OFFLINE badge on Live Tracking and on every vehicle card.
              </p>
              <NumberSetting label="Live within" value={cfg.gpsLiveThresholdS} step={5} suffix="seconds"
                             hint="Fixes newer than this are shown as LIVE."
                             onSave={(v) => save({ gpsLiveThresholdS: v }, 'GPS live threshold')} />
              <NumberSetting label="Stale until" value={cfg.gpsStaleThresholdS} step={30} suffix="seconds"
                             hint="Older than this and the vehicle is treated as offline, not merely late."
                             onSave={(v) => save({ gpsStaleThresholdS: v }, 'GPS stale threshold')} />
            </Card>

            <Card title="SLA and escalation">
              <NumberSetting label="At-risk window" value={cfg.slaAtRiskMinutes} step={5} suffix="minutes"
                             hint="A task flips to AT RISK this long before its deadline, giving dispatch time to act."
                             onSave={(v) => save({ slaAtRiskMinutes: v }, 'SLA at-risk window')} />
              <Field label="Alert escalation ladder"
                     hint="An unacknowledged alert escalates after each interval in turn.">
                <div className="chips">
                  {cfg.alertEscalationMinutes.map((m, i) => (
                    <span key={i} className="chip static">{m} min</span>
                  ))}
                </div>
              </Field>
            </Card>

            <Card title="Maintenance thresholds">
              <NumberSetting label="Due soon, distance" value={cfg.maintenanceDueSoonKm} step={100}
                             suffix="km before due"
                             hint="Schedules inside this distance are flagged as approaching."
                             onSave={(v) => save({ maintenanceDueSoonKm: v }, 'Maintenance distance threshold')} />
              <NumberSetting label="Due soon, time" value={cfg.maintenanceDueSoonDays} step={1}
                             suffix="days before due"
                             onSave={(v) => save({ maintenanceDueSoonDays: v }, 'Maintenance time threshold')} />
              <NumberSetting label="Workshop labour rate" value={cfg.labourRate} step={1}
                             suffix={`${cfg.currency} per hour`}
                             hint="Used to cost work orders and to price a maintenance window."
                             onSave={(v) => save({ labourRate: v }, 'Labour rate')} />
            </Card>

            <Card title="Document expiry warnings">
              <Field label="Warn at"
                     hint="Compliance raises an alert at each of these day counts before expiry.">
                <div className="chips">
                  {cfg.documentAlertDays.map((d) => (
                    <span key={d} className="chip static">{d} days</span>
                  ))}
                </div>
              </Field>
              <Button onClick={() => app.navigate('compliance')}>Open Compliance</Button>
            </Card>
          </div>
        )}

        {tab === 'safety' && (
          <div className="grid-2" style={{ marginTop: 14 }}>
            <Card title="Safety score weights"
                  actions={<Pill tone="warn">Re-scores all drivers on save</Pill>}>
              <p className="muted small" style={{ marginTop: 0 }}>
                Each event type costs this many points per 100 km driven. Raising a weight makes
                that behaviour matter more; every driver's score is recalculated the moment you save.
              </p>
              {Object.entries(cfg.safetyWeights).map(([kind, weight]) => (
                <NumberSetting key={kind} label={titleCase(kind)} value={weight} step={0.5}
                               suffix="points per 100 km"
                               onSave={(v) => save(
                                 { safetyWeights: { ...cfg.safetyWeights, [kind]: v } },
                                 `Safety weight for ${titleCase(kind)}`)} />
              ))}
            </Card>

            <Card title="Reward points">
              <Field label="Show leaderboard to drivers"
                     hint="When off, drivers see only their own score and badges in the driver app.">
                <Switch on={cfg.showLeaderboardToDrivers}
                        label={cfg.showLeaderboardToDrivers ? 'Visible to drivers' : 'Hidden from drivers'}
                        onChange={(on) => save({ showLeaderboardToDrivers: on },
                                               'Driver leaderboard visibility')} />
              </Field>
              <NumberSetting label="Starting balance" value={cfg.driverPointsStart} step={10}
                             suffix="points"
                             onSave={(v) => save({ driverPointsStart: v }, 'Starting points')} />
              <h4 className="micro-head">Points per event</h4>
              {Object.entries(cfg.driverPoints).map(([kind, pts]) => (
                <NumberSetting key={kind} label={titleCase(kind)} value={pts} step={1}
                               suffix="points"
                               onSave={(v) => save(
                                 { driverPoints: { ...cfg.driverPoints, [kind]: v } },
                                 `Points for ${titleCase(kind)}`)} />
              ))}
            </Card>

            <Card title="Electrification threshold">
              <NumberSetting label="Maximum daily distance" value={cfg.evCandidateDailyKm} step={10}
                             suffix="km"
                             hint="A combustion vehicle becomes an electrification candidate when its busiest single day stays under this."
                             onSave={(v) => save({ evCandidateDailyKm: v }, 'EV candidacy threshold')} />
              <Button onClick={() => app.navigate('sustainability')}>Open Sustainability</Button>
            </Card>
          </div>
        )}

        {tab === 'emissions' && (
          <div className="grid-2" style={{ marginTop: 14 }}>
            <Card title="Energy prices">
              <NumberSetting label="Diesel / petrol" value={cfg.fuelPricePerLitre} step={0.01}
                             suffix={`${cfg.currency} per litre`}
                             hint="Used to cost fuel transactions and to compare against electricity."
                             onSave={(v) => save({ fuelPricePerLitre: v }, 'Fuel price')} />
              <NumberSetting label="Electricity" value={cfg.energyPricePerKwh} step={0.01}
                             suffix={`${cfg.currency} per kWh`}
                             onSave={(v) => save({ energyPricePerKwh: v }, 'Energy price')} />
            </Card>

            <Card title="Emission factors"
                  actions={<Pill tone="warn">Changes every CO₂ figure</Pill>}>
              <NumberSetting label="Diesel" value={cfg.co2PerLitreDiesel} step={0.01}
                             suffix="kg CO₂ per litre"
                             onSave={(v) => save({ co2PerLitreDiesel: v }, 'Diesel emission factor')} />
              <NumberSetting label="Petrol" value={cfg.co2PerLitrePetrol} step={0.01}
                             suffix="kg CO₂ per litre"
                             onSave={(v) => save({ co2PerLitrePetrol: v }, 'Petrol emission factor')} />
              <NumberSetting label="Grid electricity" value={cfg.co2PerKwh} step={0.005}
                             suffix="kg CO₂ per kWh"
                             hint="Electric vehicles are not counted as zero — their charging is multiplied by this."
                             onSave={(v) => save({ co2PerKwh: v }, 'Grid emission factor')} />
              <Button onClick={() => app.navigate('sustainability')}>
                <IconRefresh size={13} /> See the effect
              </Button>
            </Card>
          </div>
        )}

        {tab === 'rules' && (
          <Card title="Alert rules" pad={false}
                actions={<span className="muted small">
                  Disabling a rule stops new alerts; existing ones stay open
                </span>}>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Rule</th><th>Category</th><th>Severity</th><th>Condition</th>
                    <th className="num">Cooldown</th><th>Notifies</th><th>Active</th>
                  </tr>
                </thead>
                <tbody>
                  {s.alertRules.map((r) => (
                    <tr key={r.id} className={r.active ? '' : 'dimmed'}>
                      <td>
                        <strong>{r.name}</strong>
                        <div className="muted small">{r.description}</div>
                      </td>
                      <td>{titleCase(r.category)}</td>
                      <td><Pill tone={r.severity === 'critical' || r.severity === 'high'
                        ? 'danger' : r.severity === 'medium' ? 'warn' : 'info'}>
                        {titleCase(r.severity)}
                      </Pill></td>
                      <td className="muted small">
                        {r.metric} {r.operator} {r.threshold ?? ''}{r.thresholdUnit ?? ''}
                        {r.durationS ? ` for ${r.durationS}s` : ''}
                      </td>
                      <td className="num">{r.cooldownS}s</td>
                      <td className="muted small">
                        {r.notifyRoles.map((x) => titleCase(x)).join(', ') || '—'}
                      </td>
                      <td>
                        <Switch on={r.active} label={r.active ? 'On' : 'Off'}
                                onChange={(on) => app.run(
                                  () => setAlertRuleActive(store, r.id, on),
                                  `Rule “${r.name}” ${on ? 'enabled' : 'disabled'}`)} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {tab === 'audit' && (
          <>
            <div className="kpis" style={{ marginTop: 14, marginBottom: 14 }}>
              <Kpi label="Entries" value={s.audit.length} />
              <Kpi label="Most recent"
                   value={s.audit.length ? relTime(s.audit[0].at, s.now) : '—'} />
              <Kpi label="Actors" value={new Set(s.audit.map((a) => a.actorName)).size} />
            </div>
            {s.audit.length ? (
              <Card title="Audit log" pad={false}
                    actions={<span className="muted small">
                      Append-only. Entries are never edited or deleted.
                    </span>}>
                <div className="table-wrap" style={{ maxHeight: 620 }}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>When</th><th>Actor</th><th>Action</th><th>Entity</th>
                        <th>Summary</th><th>Change</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s.audit.slice(0, 400).map((a) => (
                        <tr key={a.id}>
                          <td>
                            <div>{relTime(a.at, s.now)}</div>
                            <div className="muted small">
                              {new Date(a.at).toISOString().slice(5, 16).replace('T', ' ')}
                            </div>
                          </td>
                          <td>
                            {a.actorName}
                            <div className="muted small">{titleCase(a.actorRole)}</div>
                          </td>
                          <td className="mono small">{a.action}</td>
                          <td className="muted small">
                            {a.entityLabel ?? '—'}
                            {a.entityType && <div className="muted small">{a.entityType}</div>}
                          </td>
                          <td>{a.summary}</td>
                          <td className="mono small">
                            {a.before || a.after ? (
                              <details>
                                <summary className="muted">before / after</summary>
                                <pre className="diff">
{JSON.stringify({ before: a.before, after: a.after }, null, 1)}
                                </pre>
                              </details>
                            ) : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            ) : (
              <Empty title="Nothing audited yet"
                     body="Every state-changing action writes here with the actor, the entity and the before/after values." />
            )}
          </>
        )}

        {target && roleChange && (
          <Confirm title={`Change ${target.fullName}'s role?`}
                   body={`They become a ${ROLES.find((r) => r.value === roleChange.role)?.label ?? roleChange.role} immediately.`}
                   consequences={[
                     ROLES.find((r) => r.value === roleChange.role)?.blurb ?? '',
                     target.id === me.id
                       ? 'You are changing your own role — you may lose access to this page.'
                       : 'Their open sessions pick up the new permissions on their next action.',
                     'The change is recorded in the audit log with both values.',
                   ].filter(Boolean)}
                   confirmLabel="Change role"
                   tone={target.id === me.id ? 'danger' : undefined}
                   onCancel={() => setRoleChange(null)}
                   onConfirm={() => {
                     app.run(
                       () => setUserRole(store, roleChange.userId, roleChange.role as never),
                       `${target.fullName} is now a ${roleChange.role.replace('_', ' ')}`);
                     setRoleChange(null);
                   }} />
        )}
      </div>
    </div>
  );
}
