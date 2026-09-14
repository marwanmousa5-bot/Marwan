// The driver's phone, rendered inside the web console so an operator can see
// exactly what the driver sees — and drive it. Every button here runs the same
// action the dispatcher's screens run, against the same state.

import { useMemo, useState } from 'react';
import {
  INSPECTION_ITEMS, completeTaskWithPod, failTask, recordInspection, transitionTask,
} from '../../engine/actions';
import { fatigueRisk } from '../../engine/derive';
import { ACTIVE_TASK_STATUSES, leaderboard, taskSlaLabel } from '../../engine/selectors';
import type { Task } from '../../engine/types';
import { useApp, useEpoch } from '../app-context';
import {
  Avatar, Button, Card, Empty, Field, Pill, Progress, Switch, hm, relTime, titleCase,
} from '../components/kit';
import {
  IconAward, IconCamera, IconCheck, IconClock, IconClose, IconPhone, IconRoute,
  IconShield, IconTruck, IconWrench,
} from '../icons';

const FAILURE_REASONS = [
  { value: 'customer_absent', label: 'Nobody there' },
  { value: 'access_blocked', label: 'Could not access' },
  { value: 'refused', label: 'Refused by customer' },
  { value: 'damaged', label: 'Goods damaged' },
  { value: 'vehicle_issue', label: 'Vehicle problem' },
];

export function DriverApp() {
  const app = useApp();
  const epoch = useEpoch();
  const { store, state: s } = app;

  const drivers = s.drivers.filter((d) => d.status !== 'off_duty');
  const [driverId, setDriverId] = useState(
    () => (drivers[0] ?? s.drivers[0])?.id ?? '');
  const [screen, setScreen] = useState<'today' | 'check' | 'me'>('today');
  const [openTask, setOpenTask] = useState<string | null>(null);
  const [recipient, setRecipient] = useState('');
  const [podNote, setPodNote] = useState('');
  const [failReason, setFailReason] = useState('customer_absent');
  const [failNote, setFailNote] = useState('');
  const [mode, setMode] = useState<'complete' | 'fail'>('complete');
  const [items, setItems] = useState<Record<string, boolean>>(
    () => Object.fromEntries(INSPECTION_ITEMS.map((i) => [i.key, true])));
  const [checkNote, setCheckNote] = useState('');

  const driver = store.driver(driverId);
  const vehicle = s.vehicles.find((v) => v.driverId === driverId);

  const dayStart = new Date(s.now).setUTCHours(0, 0, 0, 0);
  const myTasks = useMemo(() => s.tasks
    .filter((t) => t.driverId === driverId &&
                   (ACTIVE_TASK_STATUSES.includes(t.status) ||
                    ((t.completedAt ?? t.failedAt ?? 0) >= dayStart)))
    .sort((a, b) => (a.scheduledFor ?? a.createdAt) - (b.scheduledFor ?? b.createdAt)),
    [s.tasks, driverId, dayStart, epoch]);

  const active = myTasks.filter((t) => ACTIVE_TASK_STATUSES.includes(t.status));
  const done = myTasks.filter((t) => t.status === 'completed');
  const failedToday = myTasks.filter((t) => t.status === 'failed');
  const board = useMemo(() => leaderboard(store), [store, epoch]);
  const myRank = board.find((r) => r.driver.id === driverId);
  const lastInspection = s.inspections.find(
    (i) => i.driverId === driverId && i.performedAt >= dayStart);

  const task = openTask ? store.task(openTask) : null;
  const fatigue = driver ? fatigueRisk(driver.dutyHoursToday) : 'low';

  if (!driver) {
    return <div className="scroll"><div className="page">
      <Empty title="No drivers" body="This organisation has no drivers yet." />
    </div></div>;
  }

  const advance = (t: Task, to: Task['status'], note: string) => {
    app.run(() => transitionTask(store, t, to, {
      note, actorType: 'driver', actorName: driver.fullName,
    }), note);
  };

  const nextStep = (t: Task): { to: Task['status']; label: string; note: string } | null => {
    switch (t.status) {
      case 'assigned': return { to: 'accepted', label: 'Accept job', note: 'Driver accepted the job.' };
      case 'accepted': return { to: 'en_route', label: 'Start driving', note: 'Driver set off.' };
      case 'en_route': return { to: 'arrived', label: "I've arrived", note: 'Driver arrived on site.' };
      case 'arrived': return { to: 'in_progress', label: 'Start the drop', note: 'Driver started the drop.' };
      case 'delayed': return { to: 'en_route', label: 'Back on the road', note: 'Driver resumed.' };
      default: return null;
    }
  };

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Driver app</h2>
            <p className="page-sub">
              The phone view, running against live state. Accepting a job here moves it on the
              dispatcher's board; completing one writes the proof of delivery, closes the SLA and
              updates the driver's score. Pick a driver to see their actual day.
            </p>
          </div>
          <select className="select" style={{ width: 220 }} value={driverId}
                  onChange={(e) => { setDriverId(e.target.value); setOpenTask(null); }}>
            {s.drivers.map((d) => (
              <option key={d.id} value={d.id}>
                {d.fullName} — {titleCase(d.status)}
              </option>
            ))}
          </select>
        </div>

        <div className="phone-stage">
          <div className="phone">
            <div className="phone-notch" />
            <div className="phone-screen">
              <header className="da-head">
                <Avatar name={driver.fullName} color={driver.avatarColor} size={34} />
                <div className="grow">
                  <strong>{driver.fullName.split(' ')[0]}</strong>
                  <div className="da-sub">
                    {vehicle ? `${vehicle.name} · ${vehicle.plate}` : 'No vehicle assigned'}
                  </div>
                </div>
                <Pill tone={driver.status === 'driving' ? 'moving'
                  : driver.status === 'available' ? 'good' : 'neutral'}>
                  {titleCase(driver.status)}
                </Pill>
              </header>

              <div className="da-body">
                {screen === 'today' && (
                  <>
                    <div className="da-strip">
                      <div>
                        <span className="da-metric">{active.length}</span>
                        <span className="da-label">To do</span>
                      </div>
                      <div>
                        <span className="da-metric good">{done.length}</span>
                        <span className="da-label">Done</span>
                      </div>
                      <div>
                        <span className="da-metric">{driver.dutyHoursToday.toFixed(1)} h</span>
                        <span className="da-label">On duty</span>
                      </div>
                    </div>

                    {fatigue === 'high' && (
                      <div className="da-warn">
                        <IconClock size={14} />
                        <span>
                          You have been on duty {driver.dutyHoursToday.toFixed(1)} hours. Take your
                          break before the next job.
                        </span>
                      </div>
                    )}

                    {!lastInspection && vehicle && (
                      <button className="da-cta" onClick={() => setScreen('check')}>
                        <IconWrench size={15} />
                        <span>Pre-trip check not done today</span>
                        <IconCheck size={14} />
                      </button>
                    )}

                    {!active.length && !done.length && (
                      <Empty title="Nothing scheduled"
                             body="Dispatch has not assigned you any work yet today." />
                    )}

                    {active.map((t) => {
                      const step = nextStep(t);
                      return (
                        <div key={t.id} className={`da-job ${t.slaState === 'breached' ? 'late'
                          : t.slaState === 'at_risk' ? 'risk' : ''}`}>
                          <div className="da-job-head">
                            <Pill tone={t.priority === 'urgent' ? 'danger'
                              : t.priority === 'high' ? 'warn' : 'neutral'}>
                              {titleCase(t.kind)}
                            </Pill>
                            <span className="grow" />
                            <span className="da-ref">{t.reference}</span>
                          </div>
                          <strong className="da-job-title">{t.title}</strong>
                          <div className="da-sub">{t.address}</div>
                          <div className="da-meta">
                            <span><IconClock size={11} /> {hm(t.scheduledFor)}</span>
                            <span className={t.slaState === 'breached' ? 'bad'
                              : t.slaState === 'at_risk' ? 'warn' : 'muted'}>
                              {taskSlaLabel(store, t)}
                            </span>
                            <span><IconRoute size={11} /> {titleCase(t.status)}</span>
                          </div>
                          {t.instructions && (
                            <div className="da-note">“{t.instructions}”</div>
                          )}
                          <div className="da-actions">
                            {t.contactPhone && (
                              <button className="da-btn ghost"
                                      onClick={() => app.toast('info',
                                        `Calling ${t.contactName ?? 'the customer'}`,
                                        t.contactPhone)}>
                                <IconPhone size={13} /> Call
                              </button>
                            )}
                            {step && (
                              <button className="da-btn primary"
                                      onClick={() => advance(t, step.to, step.note)}>
                                {step.label}
                              </button>
                            )}
                            {(t.status === 'in_progress' || t.status === 'arrived') && (
                              <button className="da-btn primary" onClick={() => {
                                setOpenTask(t.id); setMode('complete');
                                setRecipient(t.contactName ?? ''); setPodNote('');
                              }}>
                                <IconCamera size={13} /> Proof of delivery
                              </button>
                            )}
                            <button className="da-btn danger" onClick={() => {
                              setOpenTask(t.id); setMode('fail');
                              setFailReason('customer_absent'); setFailNote('');
                            }}>
                              Can't do it
                            </button>
                          </div>
                        </div>
                      );
                    })}

                    {!!done.length && (
                      <>
                        <h4 className="da-section">Completed today</h4>
                        {done.map((t) => (
                          <div key={t.id} className="da-done">
                            <IconCheck size={13} />
                            <div className="grow">
                              <strong>{t.title}</strong>
                              <div className="da-sub">
                                {t.pod?.recipient ? `Signed by ${t.pod.recipient} · ` : ''}
                                {relTime(t.completedAt ?? s.now, s.now)}
                              </div>
                            </div>
                            <Pill tone={t.slaState === 'met' ? 'good' : 'warn'}>
                              {t.slaState === 'met' ? 'On time' : 'Late'}
                            </Pill>
                          </div>
                        ))}
                      </>
                    )}

                    {!!failedToday.length && (
                      <>
                        <h4 className="da-section">Could not complete</h4>
                        {failedToday.map((t) => (
                          <div key={t.id} className="da-done failed">
                            <IconClose size={13} />
                            <div className="grow">
                              <strong>{t.title}</strong>
                              <div className="da-sub">
                                {titleCase(t.failureReason ?? 'unknown')}
                                {t.failureNote ? ` — ${t.failureNote}` : ''}
                              </div>
                            </div>
                          </div>
                        ))}
                      </>
                    )}
                  </>
                )}

                {screen === 'check' && (
                  <>
                    <h4 className="da-section">Pre-trip check</h4>
                    {!vehicle ? (
                      <Empty title="No vehicle"
                             body="You need a vehicle assigned before you can run a check." />
                    ) : (
                      <>
                        <div className="da-sub" style={{ marginBottom: 10 }}>
                          {vehicle.name} · {vehicle.plate} ·{' '}
                          {Math.round(vehicle.odometerKm).toLocaleString()} km
                        </div>
                        {INSPECTION_ITEMS.map((i) => (
                          <div key={i.key} className="da-check">
                            <div className="grow">
                              <strong>{i.label}</strong>
                              {i.critical && <span className="da-crit">Critical</span>}
                            </div>
                            <Switch on={items[i.key] !== false}
                                    label={items[i.key] === false ? 'Issue' : 'OK'}
                                    onChange={(on) => setItems(
                                      (prev) => ({ ...prev, [i.key]: on }))} />
                          </div>
                        ))}
                        <Field label="Anything else?">
                          <textarea className="input" rows={2} value={checkNote}
                                    placeholder="Nearside mirror is loose."
                                    onChange={(e) => setCheckNote(e.target.value)} />
                        </Field>
                        {lastInspection && (
                          <div className="da-note">
                            Last check today at {hm(lastInspection.performedAt)} —{' '}
                            {lastInspection.result === 'ready' ? 'passed' : 'issues reported'}.
                          </div>
                        )}
                        <button className="da-btn primary wide" onClick={() => {
                          app.run(() => recordInspection(store, {
                            driverId: driver.id, vehicleId: vehicle.id, items,
                            notes: checkNote.trim() || undefined,
                          }), Object.values(items).some((v) => v === false)
                            ? 'Issues reported to dispatch'
                            : 'Vehicle checked and ready');
                          setCheckNote('');
                          setScreen('today');
                        }}>
                          Submit check
                        </button>
                      </>
                    )}
                  </>
                )}

                {screen === 'me' && (
                  <>
                    <div className="da-score">
                      <div className="da-score-val">{driver.safetyScore.toFixed(1)}</div>
                      <div className="da-label">Safety score</div>
                      <Progress pct={driver.safetyScore}
                                tone={driver.safetyScore >= 85 ? 'good'
                                  : driver.safetyScore >= 70 ? 'warn' : 'danger'} />
                    </div>
                    <div className="da-strip">
                      <div>
                        <span className="da-metric">{driver.points}</span>
                        <span className="da-label">Points</span>
                      </div>
                      <div>
                        <span className="da-metric">
                          {s.org.settings.showLeaderboardToDrivers && myRank
                            ? `#${myRank.rank}` : '—'}
                        </span>
                        <span className="da-label">Rank</span>
                      </div>
                      <div>
                        <span className="da-metric">
                          {s.badges.filter((b) => b.driverId === driver.id).length}
                        </span>
                        <span className="da-label">Badges</span>
                      </div>
                    </div>

                    {!s.org.settings.showLeaderboardToDrivers && (
                      <div className="da-note">
                        Your employer has turned the leaderboard off, so you only see your own
                        numbers here.
                      </div>
                    )}

                    <h4 className="da-section">Shift</h4>
                    <div className="da-kv"><span>Duty today</span>
                      <strong>{driver.dutyHoursToday.toFixed(1)} h</strong></div>
                    <div className="da-kv"><span>Fatigue risk</span>
                      <strong className={fatigue === 'high' ? 'bad'
                        : fatigue === 'elevated' ? 'warn' : 'good'}>{titleCase(fatigue)}</strong></div>
                    <div className="da-kv"><span>Shift</span>
                      <strong>{driver.shiftStart} – {driver.shiftEnd}</strong></div>
                    <div className="da-kv"><span>Licence expires</span>
                      <strong>{driver.licenseExpiry}</strong></div>

                    <h4 className="da-section">Badges</h4>
                    {s.badges.filter((b) => b.driverId === driver.id).length ? (
                      s.badges.filter((b) => b.driverId === driver.id).slice(0, 6).map((b) => (
                        <div key={b.id} className="da-done">
                          <IconAward size={14} />
                          <div className="grow">
                            <strong>{b.name}</strong>
                            <div className="da-sub">{b.description}</div>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="da-note">No badges yet. Keep a clean week to earn one.</div>
                    )}
                  </>
                )}
              </div>

              <nav className="da-tabs">
                <button className={screen === 'today' ? 'on' : ''}
                        onClick={() => setScreen('today')}>
                  <IconRoute size={16} /><span>Today</span>
                </button>
                <button className={screen === 'check' ? 'on' : ''}
                        onClick={() => setScreen('check')}>
                  <IconWrench size={16} /><span>Check</span>
                </button>
                <button className={screen === 'me' ? 'on' : ''} onClick={() => setScreen('me')}>
                  <IconShield size={16} /><span>Me</span>
                </button>
              </nav>

              {task && (
                <div className="da-sheet">
                  <div className="da-sheet-head">
                    <strong>{mode === 'complete' ? 'Proof of delivery' : 'What happened?'}</strong>
                    <button className="da-btn ghost" onClick={() => setOpenTask(null)}>
                      <IconClose size={14} />
                    </button>
                  </div>
                  <div className="da-sheet-body">
                    <div className="da-sub">{task.reference} · {task.title}</div>
                    {mode === 'complete' ? (
                      <>
                        <Field label="Who received it?">
                          <input className="input" value={recipient}
                                 placeholder="Name of the person signing"
                                 onChange={(e) => setRecipient(e.target.value)} />
                        </Field>
                        <Field label="Notes">
                          <textarea className="input" rows={2} value={podNote}
                                    placeholder="Left at reception, second floor."
                                    onChange={(e) => setPodNote(e.target.value)} />
                        </Field>
                        <div className="da-note">
                          The delivery position is stamped from the vehicle's last GPS fix, not from
                          anything typed here.
                        </div>
                        <button className="da-btn primary wide"
                                disabled={recipient.trim().length < 2}
                                onClick={() => {
                                  app.run(() => completeTaskWithPod(store, task.id, {
                                    recipient: recipient.trim(),
                                    notes: podNote.trim() || undefined,
                                  }), `${task.reference} completed`);
                                  setOpenTask(null);
                                }}>
                          Complete job
                        </button>
                      </>
                    ) : (
                      <>
                        <Field label="Reason">
                          <select className="select" value={failReason}
                                  onChange={(e) => setFailReason(e.target.value)}>
                            {FAILURE_REASONS.map((r) => (
                              <option key={r.value} value={r.value}>{r.label}</option>
                            ))}
                          </select>
                        </Field>
                        <Field label="Detail">
                          <textarea className="input" rows={2} value={failNote}
                                    placeholder="Gate locked, no answer on the intercom."
                                    onChange={(e) => setFailNote(e.target.value)} />
                        </Field>
                        <div className="da-note">
                          This raises a high-severity alert for dispatch immediately and records the
                          failure against the job, not against you.
                        </div>
                        <button className="da-btn danger wide" onClick={() => {
                          app.run(() => failTask(store, task.id, failReason,
                                                 failNote.trim() || undefined),
                                  `${task.reference} marked as failed`);
                          setOpenTask(null);
                        }}>
                          Report it
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          <Card title="What this view proves">
            <p className="muted" style={{ marginTop: 0 }}>
              This is not a mock-up of a phone. It reads and writes the same records as every other
              page in FleetBeat:
            </p>
            <ul className="tight">
              <li><strong>Accept / start / arrive</strong> run the task state machine, so an illegal
                  transition is refused here exactly as it would be at the API.</li>
              <li><strong>Proof of delivery</strong> stamps the vehicle's last GPS position, closes
                  the SLA and marks the job on-time or late.</li>
              <li><strong>Can't do it</strong> raises a high-severity alert that appears on the
                  Alerts page within a second.</li>
              <li><strong>Pre-trip check</strong> writes an inspection record and, on a failed item,
                  raises an alert against the vehicle.</li>
              <li>The score and badges are the driver's real figures, shown only as far as the
                  organisation's leaderboard setting allows.</li>
            </ul>
            <Button onClick={() => app.navigate('tasks')}>
              <IconTruck size={13} /> Open the dispatcher's task board
            </Button>
          </Card>
        </div>
      </div>
    </div>
  );
}
