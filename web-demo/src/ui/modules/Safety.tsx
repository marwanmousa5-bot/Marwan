// Safety & Rewards — driver behaviour scoring, coaching and gamification.
//
// The score is not a black box. It is the weighted event penalty per 100 km over
// the last 30 days, and this page shows the weights, the events and the arithmetic.

import { useMemo, useState } from 'react';
import { recordDriverEvent } from '../../engine/actions';
import { fatigueRisk, safetyScore } from '../../engine/derive';
import { leaderboard } from '../../engine/selectors';
import { useApp, useEpoch } from '../app-context';
import {
  Avatar, BarChart, Button, Card, Empty, Field, HBar, Kpi, Modal, Pill, Progress,
  Tabs, Timeline, relTime, titleCase,
} from '../components/kit';
import { IconAward, IconShield, IconTrendDown, IconTrendUp } from '../icons';

const DAY = 86400000;

const EVENT_TONE: Record<string, 'danger' | 'warn' | 'good' | 'neutral'> = {
  overspeed: 'danger', harsh_braking: 'warn', harsh_acceleration: 'warn',
  harsh_cornering: 'warn', route_deviation: 'neutral', idling: 'neutral',
  geofence_breach: 'warn', clean_streak: 'good', eco_driving: 'good',
  improvement: 'good',
};

function scoreTone(score: number): 'good' | 'warn' | 'danger' {
  if (score >= 85) return 'good';
  if (score >= 70) return 'warn';
  return 'danger';
}

export function Safety() {
  const app = useApp();
  const epoch = useEpoch();
  const { store, state: s } = app;
  const [tab, setTab] = useState('leaderboard');
  const [coaching, setCoaching] = useState<string | null>(null);
  const [explain, setExplain] = useState<string | null>(null);
  const [note, setNote] = useState('');

  // The aggregation is memoised, but the ranking is re-derived on every render from
  // the live driver objects: scores change as events land, and a stale order beside
  // a fresh score would show a leaderboard that is visibly not in order.
  const aggregated = useMemo(() => leaderboard(store), [store, epoch]);
  const board = useMemo(() => [...aggregated]
    .sort((a, b) => b.driver.safetyScore - a.driver.safetyScore ||
                    b.driver.points - a.driver.points)
    .map((r, i) => ({ ...r, rank: i + 1 })), [aggregated, s.drivers, s.ticks]);

  const since30 = s.now - 30 * DAY;
  const recentEvents = useMemo(
    () => s.driverEvents.filter((e) => e.occurredAt >= since30)
      .sort((a, b) => b.occurredAt - a.occurredAt),
    [s.driverEvents, since30]);

  const byKind = useMemo(() => {
    const counts: Record<string, number> = {};
    recentEvents.forEach((e) => { counts[e.kind] = (counts[e.kind] ?? 0) + 1; });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [recentEvents]);

  const weekly = useMemo(() => {
    const buckets: { label: string; value: number }[] = [];
    for (let w = 7; w >= 0; w--) {
      const from = s.now - (w + 1) * 7 * DAY;
      const to = s.now - w * 7 * DAY;
      buckets.push({
        label: w === 0 ? 'now' : `−${w}w`,
        value: s.driverEvents.filter((e) => e.occurredAt >= from && e.occurredAt < to).length,
      });
    }
    return buckets;
  }, [s.driverEvents, s.now]);

  const fleetScore = s.drivers.length
    ? s.drivers.reduce((a, d) => a + d.safetyScore, 0) / s.drivers.length : 0;
  const declining = board.filter((r) => r.trend < -0.5);
  const improving = board.filter((r) => r.trend > 0.5);
  const fatigued = s.drivers.filter((d) => fatigueRisk(d.dutyHoursToday) === 'high' ||
                                           fatigueRisk(d.dutyHoursToday) === 'elevated');

  const coach = coaching ? store.driver(coaching) : null;
  const explained = explain ? store.driver(explain) : null;

  // Reproduce the score for one driver so the operator can see where it came from.
  const breakdown = useMemo(() => {
    if (!explained) return null;
    const events = s.driverEvents.filter(
      (e) => e.driverId === explained.id && e.occurredAt >= since30);
    const counts: Record<string, number> = {};
    events.forEach((e) => { counts[e.kind] = (counts[e.kind] ?? 0) + 1; });
    const incidents = s.incidents.filter(
      (i) => i.driverId === explained.id && i.occurredAt >= since30);
    if (incidents.length) counts.incident = incidents.length;
    const km = s.trips
      .filter((t) => t.driverId === explained.id && t.startedAt >= since30)
      .reduce((a, t) => a + t.distanceKm, 0);
    const defaults: Record<string, number> = {
      overspeed: 6, harsh_braking: 4, harsh_acceleration: 3.5, harsh_cornering: 3,
      route_deviation: 2, incident: 12,
    };
    const w = { ...defaults, ...s.org.settings.safetyWeights };
    const exposure = Math.max(km, 25) / 100;
    const rows = Object.entries(counts)
      .filter(([k]) => (w[k] ?? 1) > 0)
      .map(([kind, n]) => ({
        kind, count: n, weight: w[kind] ?? 1, penalty: ((w[kind] ?? 1) * n) / exposure,
      }))
      .sort((a, b) => b.penalty - a.penalty);
    return {
      km, exposure, rows,
      totalPenalty: rows.reduce((a, r) => a + r.penalty, 0),
      score: safetyScore(counts, km, s.org.settings.safetyWeights),
    };
  }, [explained, s.driverEvents, s.trips, s.incidents, s.org, since30]);

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Safety &amp; Rewards</h2>
            <p className="page-sub">
              Scores are recalculated from the last 30 days every time an event lands. A driver who
              covers more distance is not punished for it — penalties are normalised per 100 km.
            </p>
          </div>
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="Fleet safety score" value={fleetScore.toFixed(1)} unit="/100"
               tone={scoreTone(fleetScore) === 'good' ? 'good' : scoreTone(fleetScore)} />
          <Kpi label="Events, 30 days" value={recentEvents.length} />
          <Kpi label="Improving" value={improving.length} tone={improving.length ? 'good' : undefined} />
          <Kpi label="Declining" value={declining.length}
               tone={declining.length ? 'danger' : undefined}
               onClick={() => setTab('coaching')} />
          <Kpi label="Fatigue watch" value={fatigued.length}
               tone={fatigued.length ? 'warn' : undefined} />
          <Kpi label="Badges awarded" value={s.badges.length} />
        </div>

        <Tabs active={tab} onChange={setTab} tabs={[
          { key: 'leaderboard', label: 'Leaderboard' },
          { key: 'events', label: `Events (${recentEvents.length})` },
          { key: 'coaching', label: `Coaching (${declining.length})` },
          { key: 'rewards', label: 'Rewards' },
        ]} />

        {tab === 'leaderboard' && (
          <>
            <div className="grid-2" style={{ marginTop: 14 }}>
              <Card title="Events per week, fleet-wide">
                <BarChart data={weekly} tone="var(--warn)" format={(v) => `${v} events`} />
              </Card>
              <Card title="What kind of events">
                {byKind.length
                  ? byKind.map(([kind, n]) => (
                      <HBar key={kind} label={titleCase(kind)} value={n}
                            max={byKind[0][1]}
                            tone={EVENT_TONE[kind] === 'good' ? 'var(--good)'
                              : EVENT_TONE[kind] === 'danger' ? 'var(--bad)' : 'var(--warn)'} />
                    ))
                  : <Empty title="No events in 30 days"
                           body="Either the fleet is driving cleanly or nothing has run yet." />}
              </Card>
            </div>

            <Card title="Driver leaderboard — this month" pad={false}
                  actions={<span className="muted small">
                    Ranked by safety score, then reward points
                  </span>}>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th style={{ width: 52 }}>#</th><th>Driver</th><th>Status</th>
                      <th>Score</th><th className="num">Trend</th>
                      <th className="num">Distance</th><th className="num">Events</th>
                      <th className="num">Points</th><th className="num">Badges</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {board.map((r) => (
                      <tr key={r.driver.id} className="clickable"
                          onClick={() => app.open('driver', r.driver.id)}>
                        <td>
                          <span className={`rank rank-${r.rank <= 3 ? r.rank : 'n'}`}>
                            {r.rank}
                          </span>
                        </td>
                        <td>
                          <div className="row-flex">
                            <Avatar name={r.driver.fullName} color={r.driver.avatarColor} />
                            <div>
                              <strong>{r.driver.fullName}</strong>
                              <div className="muted small">{r.driver.employeeNo}</div>
                            </div>
                          </div>
                        </td>
                        <td><Pill tone={r.driver.status === 'driving' ? 'moving'
                          : r.driver.status === 'off_duty' ? 'neutral' : 'info'}>
                          {titleCase(r.driver.status)}
                        </Pill></td>
                        <td style={{ minWidth: 130 }}>
                          <div className="score-cell">
                            <strong className="num">{r.driver.safetyScore.toFixed(1)}</strong>
                            <Progress pct={r.driver.safetyScore}
                                      tone={scoreTone(r.driver.safetyScore)} />
                          </div>
                        </td>
                        <td className={`num ${r.trend > 0 ? 'good' : r.trend < 0 ? 'bad' : 'muted'}`}>
                          {r.trend === 0 ? '—' : <>
                            {r.trend > 0 ? <IconTrendUp size={12} /> : <IconTrendDown size={12} />}
                            {' '}{r.trend > 0 ? '+' : ''}{r.trend.toFixed(1)}
                          </>}
                        </td>
                        <td className="num">{Math.round(r.distanceKm).toLocaleString()} km</td>
                        <td className="num">{r.events}</td>
                        <td className="num">{r.driver.points}</td>
                        <td className="num">{r.badges}</td>
                        <td onClick={(e) => e.stopPropagation()}>
                          <Button size="sm" onClick={() => setExplain(r.driver.id)}>
                            Why this score
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        )}

        {tab === 'events' && (
          <Card title={`Safety events — last 30 days`} pad={false}>
            {recentEvents.length ? (
              <div className="table-wrap" style={{ maxHeight: 620 }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>When</th><th>Driver</th><th>Vehicle</th><th>Event</th>
                      <th>Where</th><th className="num">Measured</th><th>Severity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentEvents.slice(0, 400).map((e) => {
                      const d = store.driver(e.driverId);
                      const v = e.vehicleId ? store.vehicle(e.vehicleId) : null;
                      return (
                        <tr key={e.id} className={e.lat ? 'clickable' : ''}
                            onClick={() => { if (e.lat) app.focusMap(e.lat, e.lon!, 16); }}>
                          <td>
                            <div>{relTime(e.occurredAt, s.now)}</div>
                            <div className="muted small">
                              {new Date(e.occurredAt).toISOString().slice(5, 16).replace('T', ' ')}
                            </div>
                          </td>
                          <td>{d?.fullName ?? '—'}</td>
                          <td>{v ? `${v.name} · ${v.plate}` : '—'}</td>
                          <td><Pill tone={EVENT_TONE[e.kind] ?? 'neutral'}>
                            {titleCase(e.kind)}
                          </Pill></td>
                          <td className="muted">{e.street ?? '—'}</td>
                          <td className="num">
                            {e.value != null
                              ? `${Math.round(e.value)}${e.threshold != null
                                  ? ` / ${Math.round(e.threshold)}` : ''}`
                              : e.durationS != null ? `${Math.round(e.durationS)}s` : '—'}
                          </td>
                          <td><Pill tone={e.severity === 'critical' || e.severity === 'high'
                            ? 'danger' : e.severity === 'medium' ? 'warn' : 'neutral'}>
                            {titleCase(e.severity)}
                          </Pill></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div style={{ padding: 18 }}>
                <Empty title="No safety events recorded"
                       body="The last 30 days are clean. Events appear here the moment the telemetry stream detects one." />
              </div>
            )}
          </Card>
        )}

        {tab === 'coaching' && (
          declining.length ? (
            <div className="card-grid" style={{ marginTop: 14 }}>
              {declining.map((r) => {
                const worst = (() => {
                  const counts: Record<string, number> = {};
                  s.driverEvents
                    .filter((e) => e.driverId === r.driver.id && e.occurredAt >= since30)
                    .forEach((e) => { counts[e.kind] = (counts[e.kind] ?? 0) + 1; });
                  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
                })();
                return (
                  <Card key={r.driver.id}
                        title={<h3 className="row-flex">
                          <Avatar name={r.driver.fullName} color={r.driver.avatarColor} />
                          {r.driver.fullName}
                        </h3>}
                        actions={<Button size="sm" variant="primary"
                                         onClick={() => { setCoaching(r.driver.id); setNote(''); }}>
                          Log coaching
                        </Button>}>
                    <dl className="dl">
                      <dt>Score now</dt>
                      <dd className="num bad">{r.driver.safetyScore.toFixed(1)}</dd>
                      <dt>Was</dt>
                      <dd className="num">{r.driver.previousSafetyScore.toFixed(1)}</dd>
                      <dt>Change</dt>
                      <dd className="num bad">{r.trend.toFixed(1)}</dd>
                      <dt>Events, 30 d</dt><dd className="num">{r.events}</dd>
                      <dt>Main issue</dt>
                      <dd>{worst ? `${titleCase(worst[0])} × ${worst[1]}` : '—'}</dd>
                      <dt>Duty today</dt>
                      <dd className="num">{r.driver.dutyHoursToday.toFixed(1)} h ·{' '}
                        {titleCase(fatigueRisk(r.driver.dutyHoursToday))} fatigue risk</dd>
                    </dl>
                  </Card>
                );
              })}
            </div>
          ) : (
            <Empty title="No driver is trending downwards"
                   body="Coaching candidates appear here automatically when a driver's score falls against their own previous figure." />
          )
        )}

        {tab === 'rewards' && (
          <div className="grid-2" style={{ marginTop: 14 }}>
            <Card title="Points earned and lost" pad={false}>
              {s.pointTransactions.length ? (
                <div className="table-wrap" style={{ maxHeight: 460 }}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>When</th><th>Driver</th><th>Reason</th>
                        <th className="num">Points</th><th className="num">Balance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s.pointTransactions.slice(0, 200).map((t) => (
                        <tr key={t.id}>
                          <td>{relTime(t.occurredAt, s.now)}</td>
                          <td>{store.driver(t.driverId)?.fullName ?? '—'}</td>
                          <td>{titleCase(t.reason)}</td>
                          <td className={`num ${t.points > 0 ? 'good' : 'bad'}`}>
                            {t.points > 0 ? '+' : ''}{t.points}
                          </td>
                          <td className="num">{t.balanceAfter}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ padding: 18 }}>
                  <Empty title="No point movements yet"
                         body="Points move when events are recorded and when clean streaks complete." />
                </div>
              )}
            </Card>

            <Card title={`Badges (${s.badges.length})`}>
              {s.badges.length ? (
                <div className="badge-grid">
                  {s.badges.slice(0, 40).map((b) => (
                    <div key={b.id} className="badge-card">
                      <div className="badge-icon"><IconAward size={18} /></div>
                      <div>
                        <strong>{b.name}</strong>
                        <div className="muted small">{b.description}</div>
                        <div className="muted small">
                          {store.driver(b.driverId)?.fullName} · {b.period}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <Empty title="No badges awarded yet"
                       body="Badges are granted for clean streaks, fuel efficiency and on-time delivery runs." />
              )}
              <p className="muted small" style={{ marginTop: 12 }}>
                Drivers {s.org.settings.showLeaderboardToDrivers ? 'can' : 'cannot'} see the
                leaderboard in the driver app. Change that in Settings → Rewards.
              </p>
            </Card>
          </div>
        )}

        {coach && (
          <Modal title={`Log a coaching session — ${coach.fullName}`}
                 subtitle="Recorded against the driver as an improvement event, and written to the audit log."
                 onClose={() => setCoaching(null)}
                 footer={<>
                   <Button onClick={() => setCoaching(null)}>Cancel</Button>
                   <Button variant="primary" disabled={note.trim().length < 5} onClick={() => {
                     app.run(() => {
                       recordDriverEvent(store, {
                         driverId: coach.id, kind: 'improvement', severity: 'low',
                         detail: `Coaching session: ${note.trim()}`,
                       });
                       store.audit({
                         action: 'driver.coached', entityType: 'driver',
                         entityLabel: coach.fullName,
                         summary: `Coaching session logged for ${coach.fullName}`,
                       });
                       store.emit();
                     }, `Coaching logged for ${coach.fullName}`);
                     setCoaching(null);
                   }}>Log session</Button>
                 </>}>
            <div className="banner info" style={{ marginBottom: 12 }}>
              <IconShield size={16} />
              <div>
                Coaching does not erase past events. It is recorded on the driver's timeline so the
                next review can see what was discussed and when.
              </div>
            </div>
            <Field label="What was discussed"
                   hint="Be specific — this is what the next reviewer will read.">
              <textarea className="input" rows={4} value={note}
                        placeholder="Reviewed three harsh-braking events on Mannerheimintie; agreed to increase following distance in wet conditions."
                        onChange={(e) => setNote(e.target.value)} />
            </Field>
            <Card title="Recent events for this driver" pad={false}>
              <div style={{ padding: '10px 14px' }}>
                <Timeline entries={s.driverEvents
                  .filter((e) => e.driverId === coach.id && e.occurredAt >= since30)
                  .sort((a, b) => b.occurredAt - a.occurredAt)
                  .slice(0, 8)
                  .map((e) => ({
                    id: e.id, occurredAt: e.occurredAt, actorType: 'system',
                    actorName: 'Telematics', 
                    description: `${titleCase(e.kind)}${e.street ? ` on ${e.street}` : ''}` +
                      (e.detail ? ` — ${e.detail}` : ''),
                  }))} />
              </div>
            </Card>
          </Modal>
        )}

        {explained && breakdown && (
          <Modal title={`How ${explained.fullName}'s score is calculated`}
                 subtitle="Last 30 days · penalty per 100 km, subtracted from 100"
                 onClose={() => setExplain(null)}
                 footer={<Button variant="primary" onClick={() => setExplain(null)}>Close</Button>}>
            <div className="kpis" style={{ marginBottom: 14 }}>
              <Kpi label="Score" value={breakdown.score.toFixed(1)} unit="/100"
                   tone={scoreTone(breakdown.score)} />
              <Kpi label="Distance, 30 d"
                   value={Math.round(breakdown.km).toLocaleString()} unit=" km" />
              <Kpi label="Total penalty" value={breakdown.totalPenalty.toFixed(1)} />
            </div>
            {breakdown.rows.length ? (
              <Card title="Penalty by event type" pad={false}>
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Event</th><th className="num">Count</th>
                        <th className="num">Weight</th><th className="num">Penalty</th>
                      </tr>
                    </thead>
                    <tbody>
                      {breakdown.rows.map((r) => (
                        <tr key={r.kind}>
                          <td>{titleCase(r.kind)}</td>
                          <td className="num">{r.count}</td>
                          <td className="num">{r.weight}</td>
                          <td className="num">−{r.penalty.toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr>
                        <td colSpan={3}><strong>Total</strong></td>
                        <td className="num"><strong>−{breakdown.totalPenalty.toFixed(2)}</strong></td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </Card>
            ) : (
              <Empty title="No penalised events"
                     body="This driver has a clean 30-day window, so the score sits at 100." />
            )}
            <p className="muted small" style={{ marginTop: 12 }}>
              Exposure divisor: {breakdown.exposure.toFixed(2)} (distance ÷ 100, floored at 25 km so
              a driver with almost no distance cannot be destroyed by a single event). Weights are
              editable in Settings → Safety scoring, and changing them re-scores every driver.
            </p>
          </Modal>
        )}
      </div>
    </div>
  );
}
