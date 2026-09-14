// Analytics — every chart answers a question a fleet manager actually asks.

import { useMemo, useState } from 'react';
import { csvFor, periodReport } from '../../engine/intelligence';
import { analytics, fuelSummary } from '../../engine/selectors';
import { useApp, useEpoch } from '../app-context';
import {
  BarChart, Button, Card, Donut, HBar, Kpi, Modal, Progress, Sparkline, Tabs,
  dmy, titleCase,
} from '../components/kit';
import { IconDownload, IconTrendDown, IconTrendUp } from '../icons';

export function Analytics() {
  const app = useApp();
  const epoch = useEpoch();
  const { store, state: s } = app;
  const [days, setDays] = useState(30);
  const [tab, setTab] = useState('fleet');
  const [report, setReport] = useState<7 | 30 | null>(null);
  const [exported, setExported] = useState<{ name: string; csv: string } | null>(null);

  const a = useMemo(() => analytics(store, days), [store, days, epoch]);
  const fuel = useMemo(() => fuelSummary(store, days), [store, days, epoch]);

  const distanceSeries = a.daily.map((d) => ({ label: d.day.slice(5), value: d.km }));
  const taskSeries = a.daily.map((d) => ({ label: d.day.slice(5), value: d.tasks }));
  const eventSeries = a.daily.map((d) => ({ label: d.day.slice(5), value: d.events }));

  const exportCsv = (name: string, columns: string[], rows: (string | number)[][]) => {
    setExported({ name, csv: csvFor(columns, rows) });
  };

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Analytics</h2>
            <p className="page-sub">
              How the fleet is performing. Every figure is computed from the same
              operating record the rest of FleetBeat uses.
            </p>
          </div>
          <select className="select" style={{ width: 150 }} value={days}
                  onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 30, 90, 180].map((d) => <option key={d} value={d}>Last {d} days</option>)}
          </select>
          <Button onClick={() => setReport(7)}>Weekly report</Button>
          <Button variant="primary" onClick={() => setReport(30)}>Monthly report</Button>
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="Distance" value={Math.round(a.distanceKm).toLocaleString()} unit=" km" />
          <Kpi label="Trips" value={a.trips} />
          <Kpi label="Utilisation" value={Math.round(a.utilisationPct)} unit="%"
               foot={`${a.operatingDays} operating day${a.operatingDays === 1 ? '' : 's'}`} />
          <Kpi label="Availability" value={a.availabilityPct.toFixed(0)} unit="%"
               tone={a.availabilityPct >= 85 ? 'good' : 'warn'} />
          <Kpi label="Tasks completed" value={a.tasksCompleted} tone="good" />
          <Kpi label="Completion rate" value={a.completionRate.toFixed(1)} unit="%" />
          <Kpi label="SLA compliance" value={a.slaCompliance.toFixed(1)} unit="%"
               tone={a.slaCompliance >= 95 ? 'good' : a.slaCompliance >= 85 ? 'warn' : 'danger'} />
          <Kpi label="Idle share" value={a.idleSharePct.toFixed(1)} unit="%"
               tone={a.idleSharePct > 25 ? 'warn' : undefined} />
        </div>

        <Tabs tabs={[
          { key: 'fleet', label: 'Fleet' },
          { key: 'operations', label: 'Operations' },
          { key: 'safety', label: 'Safety' },
          { key: 'maintenance', label: 'Maintenance' },
          { key: 'fuel', label: 'Fuel' },
        ]} active={tab} onChange={setTab} />

        <div style={{ paddingTop: 14 }}>
          {tab === 'fleet' && (
            <div className="stack">
              <Card title="Distance per day"
                    actions={<Button size="sm" onClick={() => exportCsv(
                      'distance-per-day',
                      ['Day', 'Distance km', 'Trips', 'Tasks completed', 'Events', 'CO2 kg'],
                      a.daily.map((d) => [d.day, d.km.toFixed(1), d.trips, d.tasks, d.events,
                                          d.co2.toFixed(1)]))}>
                      <IconDownload size={13} /> CSV
                    </Button>}>
                <BarChart data={distanceSeries} height={170}
                          format={(v) => `${Math.round(v)} km`} />
              </Card>

              <div className="grid-2">
                <Card title="Vehicle utilisation"
                      actions={<span className="dim" style={{ fontSize: 11 }}>
                        On-duty hours against a 10-hour operating day
                      </span>}>
                  {a.utilisation.slice(0, 12).map((u) => (
                    <HBar key={u.vehicle.id}
                          label={`${u.vehicle.name} · ${u.vehicle.plate}`}
                          value={u.utilisationPct} max={100}
                          format={(v) => `${Math.round(v)}% · ${u.dutyHours.toFixed(0)} h out, ` +
                            `${u.hours.toFixed(0)} h driving`}
                          tone={u.utilisationPct > 60 ? 'var(--success)'
                            : u.utilisationPct > 30 ? 'var(--pulse)' : 'var(--warning)'} />
                  ))}
                </Card>
                <Card title="Fleet mix">
                  <Donut size={140}
                         segments={Object.entries(
                           s.vehicles.reduce((acc, v) => {
                             acc[v.type] = (acc[v.type] ?? 0) + 1;
                             return acc;
                           }, {} as Record<string, number>))
                           .map(([k, v], i) => ({
                             label: titleCase(k), value: v,
                             color: ['#1E90FF', '#2ECC71', '#F5A623', '#9B6BFF',
                                     '#FF6B35', '#2FB8D9'][i % 6],
                           }))}
                         centerValue={String(s.vehicles.length)} centerLabel="vehicles" />
                  <dl className="kv" style={{ marginTop: 12 }}>
                    <dt>Driving hours</dt><dd className="num">{a.drivingHours.toFixed(0)} h</dd>
                    <dt>Idle hours</dt><dd className="num">{a.idleHours.toFixed(0)} h</dd>
                    <dt>Average speed</dt><dd className="num">{a.avgSpeedKph.toFixed(1)} km/h</dd>
                  </dl>
                </Card>
              </div>
            </div>
          )}

          {tab === 'operations' && (
            <div className="stack">
              <Card title="Tasks completed per day">
                <BarChart data={taskSeries} height={160} tone="var(--success)" />
              </Card>
              <div className="grid-2">
                <Card title="Task outcomes">
                  <Donut size={140}
                         segments={[
                           { label: 'Completed', value: a.tasksCompleted, color: '#2ECC71' },
                           { label: 'Failed', value: a.tasksFailed, color: '#E74C3C' },
                           { label: 'Still open',
                             value: Math.max(0, a.tasksCreated - a.tasksCompleted - a.tasksFailed),
                             color: '#1E90FF' },
                         ]}
                         centerValue={`${a.completionRate.toFixed(0)}%`} centerLabel="completed" />
                </Card>
                <Card title="SLA performance">
                  <div style={{ marginBottom: 12 }}>
                    <div className="row" style={{ fontSize: 12.5, marginBottom: 5 }}>
                      <span className="grow">Compliance over {days} days</span>
                      <span className="num">{a.slaCompliance.toFixed(1)}%</span>
                    </div>
                    <Progress pct={a.slaCompliance}
                              tone={a.slaCompliance >= 95 ? 'good'
                                : a.slaCompliance >= 85 ? 'warn' : 'danger'} />
                  </div>
                  <dl className="kv">
                    <dt>Tasks created</dt><dd className="num">{a.tasksCreated}</dd>
                    <dt>Completed</dt><dd className="num">{a.tasksCompleted}</dd>
                    <dt>Failed</dt><dd className="num">{a.tasksFailed}</dd>
                    <dt>Currently breached</dt>
                    <dd className="num">{s.tasks.filter((t) => t.slaState === 'breached').length}</dd>
                    <dt>Currently at risk</dt>
                    <dd className="num">{s.tasks.filter((t) => t.slaState === 'at_risk').length}</dd>
                  </dl>
                </Card>
              </div>
              <Card pad={false} title="Task completion by driver"
                    actions={<Button size="sm" onClick={() => exportCsv(
                      'driver-performance',
                      ['Driver', 'Completed', 'Failed', 'Distance km', 'Safety score'],
                      s.drivers.map((d) => {
                        const done = s.tasks.filter((t) => t.driverId === d.id &&
                          t.status === 'completed').length;
                        const failed = s.tasks.filter((t) => t.driverId === d.id &&
                          t.status === 'failed').length;
                        const km = s.trips.filter((t) => t.driverId === d.id)
                          .reduce((x, t) => x + t.distanceKm, 0);
                        return [d.fullName, done, failed, km.toFixed(0), d.safetyScore];
                      }))}>
                      <IconDownload size={13} /> CSV
                    </Button>}>
                <div className="table-wrap">
                  <table className="data">
                    <thead><tr><th>Driver</th><th className="num">Completed</th>
                               <th className="num">Failed</th><th className="num">On time</th>
                               <th className="num">Distance</th></tr></thead>
                    <tbody>
                      {s.drivers.map((d) => {
                        const tasks = s.tasks.filter((t) => t.driverId === d.id);
                        const done = tasks.filter((t) => t.status === 'completed');
                        const failed = tasks.filter((t) => t.status === 'failed').length;
                        const met = done.filter((t) => t.slaState === 'met').length;
                        const km = s.trips.filter((t) => t.driverId === d.id)
                          .reduce((x, t) => x + t.distanceKm, 0);
                        return (
                          <tr key={d.id} data-clickable="true" onClick={() => app.open('driver', d.id)}>
                            <td>{d.fullName}</td>
                            <td className="num">{done.length}</td>
                            <td className="num">{failed}</td>
                            <td className="num">
                              {done.length ? `${Math.round((met / done.length) * 100)}%` : '—'}
                            </td>
                            <td className="num">{Math.round(km).toLocaleString()} km</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>
            </div>
          )}

          {tab === 'safety' && (
            <div className="stack">
              <Card title="Safety events per day">
                <BarChart data={eventSeries} height={150} tone="var(--warning)" />
              </Card>
              <div className="grid-2">
                <Card title="Event mix">
                  {Object.keys(a.eventCounts).length === 0 ? (
                    <p className="muted" style={{ margin: 0 }}>
                      No safety events recorded in this period.
                    </p>
                  ) : (
                    Object.entries(a.eventCounts).sort((x, y) => y[1] - x[1]).map(([k, n]) => (
                      <HBar key={k} label={titleCase(k)} value={n}
                            max={Math.max(...Object.values(a.eventCounts))}
                            tone={k === 'overspeed' ? 'var(--danger)' : 'var(--warning)'} />
                    ))
                  )}
                </Card>
                <Card title="Driver safety scores">
                  {[...s.drivers].sort((x, y) => y.safetyScore - x.safetyScore).map((d) => (
                    <HBar key={d.id} label={d.fullName} value={d.safetyScore} max={100}
                          format={(v) => v.toFixed(1)}
                          tone={d.safetyScore >= 85 ? 'var(--success)'
                            : d.safetyScore >= 70 ? 'var(--warning)' : 'var(--danger)'} />
                  ))}
                </Card>
              </div>
              <Card pad={false} title="Trends">
                <div className="table-wrap">
                  <table className="data">
                    <thead><tr><th>Driver</th><th className="num">Score</th>
                               <th className="num">Change</th><th>Direction</th>
                               <th className="num">Events (period)</th></tr></thead>
                    <tbody>
                      {[...s.drivers]
                        .sort((x, y) => (x.safetyScore - x.previousSafetyScore) -
                                        (y.safetyScore - y.previousSafetyScore))
                        .map((d) => {
                          const delta = d.safetyScore - d.previousSafetyScore;
                          const n = s.driverEvents.filter(
                            (e) => e.driverId === d.id &&
                                   e.occurredAt >= s.now - days * 86400000).length;
                          return (
                            <tr key={d.id} data-clickable="true" onClick={() => app.open('driver', d.id)}>
                              <td>{d.fullName}</td>
                              <td className="num">{d.safetyScore.toFixed(1)}</td>
                              <td className="num" style={{
                                color: delta > 0 ? 'var(--success)'
                                  : delta < 0 ? 'var(--danger)' : undefined,
                              }}>{delta > 0 ? '+' : ''}{delta.toFixed(1)}</td>
                              <td>
                                {Math.abs(delta) < 0.3 ? <span className="dim">Steady</span>
                                  : delta > 0
                                    ? <span className="row" style={{ gap: 5, color: 'var(--success)' }}>
                                        <IconTrendUp size={13} /> Improving
                                      </span>
                                    : <span className="row" style={{ gap: 5, color: 'var(--danger)' }}>
                                        <IconTrendDown size={13} /> Declining
                                      </span>}
                              </td>
                              <td className="num">{n}</td>
                            </tr>
                          );
                        })}
                    </tbody>
                  </table>
                </div>
              </Card>
            </div>
          )}

          {tab === 'maintenance' && (
            <div className="stack">
              <div className="grid-2">
                <Card title="Maintenance spend by month">
                  <BarChart height={160} tone="#9B6BFF"
                            format={(v) => `€${Math.round(v)}`}
                            data={(() => {
                              const m = new Map<string, number>();
                              for (let i = 5; i >= 0; i--) {
                                m.set(new Date(s.now - i * 30 * 86400000).toISOString().slice(0, 7), 0);
                              }
                              s.maintenanceRecords.forEach((r) => {
                                const k = r.serviceDate.slice(0, 7);
                                if (m.has(k)) m.set(k, m.get(k)! + r.totalCost);
                              });
                              return [...m.entries()].map(([k, v]) => ({ label: k.slice(5), value: v }));
                            })()} />
                </Card>
                <Card title="Downtime by vehicle">
                  {(() => {
                    const byVehicle: Record<string, number> = {};
                    s.maintenanceRecords.forEach((r) => {
                      byVehicle[r.vehicleId] = (byVehicle[r.vehicleId] ?? 0) + r.downtimeHours;
                    });
                    const max = Math.max(1, ...Object.values(byVehicle));
                    return Object.entries(byVehicle)
                      .sort((x, y) => y[1] - x[1]).slice(0, 10)
                      .map(([vid, hours]) => (
                        <HBar key={vid} label={store.vehicle(vid)?.name ?? '—'}
                              value={hours} max={max}
                              format={(v) => `${v.toFixed(0)} h`} tone="#9B6BFF" />
                      ));
                  })()}
                </Card>
              </div>
              <Card pad={false} title="Failure frequency and cost">
                <div className="table-wrap">
                  <table className="data">
                    <thead><tr><th>Vehicle</th><th className="num">Services</th>
                               <th className="num">Total cost</th><th className="num">Cost/service</th>
                               <th className="num">Downtime</th>
                               <th className="num">Failures / 10,000 km</th></tr></thead>
                    <tbody>
                      {s.vehicles.map((v) => {
                        const recs = s.maintenanceRecords.filter((r) => r.vehicleId === v.id);
                        if (!recs.length) return null;
                        const total = recs.reduce((x, r) => x + r.totalCost, 0);
                        const downtime = recs.reduce((x, r) => x + r.downtimeHours, 0);
                        const span = Math.max(1, v.odometerKm -
                          Math.min(...recs.map((r) => r.odometerKm)));
                        return (
                          <tr key={v.id} data-clickable="true" onClick={() => app.open('vehicle', v.id)}>
                            <td>{v.name} <span className="mono dim">{v.plate}</span></td>
                            <td className="num">{recs.length}</td>
                            <td className="num">€{Math.round(total).toLocaleString()}</td>
                            <td className="num">€{Math.round(total / recs.length)}</td>
                            <td className="num">{downtime.toFixed(0)} h</td>
                            <td className="num">{((recs.length / span) * 10000).toFixed(2)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>
            </div>
          )}

          {tab === 'fuel' && (
            <div className="stack">
              <div className="kpis">
                <Kpi label="Fuel" value={Math.round(fuel.litres).toLocaleString()} unit=" L" />
                <Kpi label="Energy" value={Math.round(fuel.kwh).toLocaleString()} unit=" kWh" />
                <Kpi label="Spend" value={`€${Math.round(fuel.totalCost).toLocaleString()}`} />
                <Kpi label="Average consumption"
                     value={fuel.avgLPer100 ? fuel.avgLPer100.toFixed(1) : '—'} unit=" L/100km" />
                <Kpi label="Cost per km"
                     value={fuel.costPerKm ? `€${fuel.costPerKm.toFixed(3)}` : '—'} />
              </div>
              <Card title="Consumption by vehicle"
                    actions={<Button size="sm" onClick={() => exportCsv(
                      'fuel-efficiency',
                      ['Vehicle', 'Plate', 'Fuel type', 'Distance km', 'Consumption',
                       'Unit', 'Cost', 'Cost per km'],
                      fuel.perVehicle.map((r) => [
                        r.vehicle.name, r.vehicle.plate, r.vehicle.fuelType,
                        r.distanceKm.toFixed(0), r.efficiency?.toFixed(2) ?? '',
                        r.unit, r.totalCost.toFixed(2), r.costPerKm?.toFixed(3) ?? '']))}>
                      <IconDownload size={13} /> CSV
                    </Button>}>
                {fuel.perVehicle.filter((r) => r.efficiency).map((r) => (
                  <HBar key={r.vehicle.id} label={`${r.vehicle.name} · ${r.unit}`}
                        value={r.efficiency ?? 0}
                        max={Math.max(...fuel.perVehicle.map((x) => x.efficiency ?? 0), 1)}
                        format={(v) => v.toFixed(1)}
                        tone={r.electric ? 'var(--success)' : 'var(--pulse)'} />
                ))}
              </Card>
            </div>
          )}
        </div>
      </div>

      {report && <ReportModal days={report} onClose={() => setReport(null)} />}
      {exported && (
        <Modal title={`Export — ${exported.name}.csv`} size="lg"
               onClose={() => setExported(null)}
               subtitle="Downloads are blocked inside this preview, so the CSV is shown here to copy."
               footer={<>
                 <Button onClick={() => setExported(null)}>Close</Button>
                 <Button variant="primary" onClick={() => {
                   navigator.clipboard?.writeText(exported.csv)
                     .then(() => app.toast('success', 'CSV copied to the clipboard'))
                     .catch(() => app.toast('error', 'The browser blocked clipboard access.',
                                            'Select the text and copy it manually.'));
                 }}>Copy CSV</Button>
               </>}>
          <pre className="mono" style={{
            margin: 0, fontSize: 11, maxHeight: 420, overflow: 'auto',
            background: 'var(--sunken)', padding: 12, borderRadius: 7,
          }}>{exported.csv}</pre>
        </Modal>
      )}
    </div>
  );
}

function ReportModal({ days, onClose }: { days: 7 | 30; onClose: () => void }) {
  const app = useApp();
  const report = useMemo(() => periodReport(app.store, days), [app.store, days]);
  return (
    <Modal title={`${report.period} — automated report`} size="lg" onClose={onClose}
           subtitle={`Generated ${dmy(report.generatedAt)} from this organization's own operating record.`}
           footer={<Button variant="primary" onClick={onClose}>Close</Button>}>
      <div className="stack">
        <Card title="What happened">
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.8 }}>
            {report.happened.map((line, i) => <li key={i}>{line}</li>)}
          </ul>
        </Card>
        <div className="grid-2">
          <Card title="What improved">
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.8,
                         color: 'var(--success)' }}>
              {report.improved.map((line, i) => <li key={i}>{line}</li>)}
            </ul>
          </Card>
          <Card title="What deteriorated">
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.8,
                         color: 'var(--danger)' }}>
              {report.deteriorated.map((line, i) => <li key={i}>{line}</li>)}
            </ul>
          </Card>
        </div>
        <Card title="Biggest risks">
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.8 }}>
            {report.risks.map((line, i) => <li key={i}>{line}</li>)}
          </ul>
        </Card>
        <Card title="Recommended actions">
          <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.8 }}>
            {report.actions.map((line, i) => <li key={i}>{line}</li>)}
          </ol>
        </Card>
        <Card title="Distance trend">
          <Sparkline points={report.metrics.daily.map((d) => d.km)} height={52} />
        </Card>
      </div>
    </Modal>
  );
}
