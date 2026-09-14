// Fuel & Energy, including EV charging and the energy view of the fleet.

import { useMemo, useState } from 'react';
import { recordFuel } from '../../engine/actions';
import { fuelSummary } from '../../engine/selectors';
import { useApp, useEpoch } from '../app-context';
import {
  BarChart, Button, Card, Empty, Field, HBar, Kpi, Modal, Money, Pill, Tabs,
  dmy, titleCase,
} from '../components/kit';
import { IconBattery, IconFuel, IconPlus } from '../icons';

const DAY = 86400000;

export function Fuel() {
  const app = useApp();
  const epoch = useEpoch();
  const { store, state: s } = app;
  const [days, setDays] = useState(30);
  const [tab, setTab] = useState('overview');
  const [recording, setRecording] = useState(false);

  const summary = useMemo(() => fuelSummary(store, days), [store, days, epoch]);
  const evs = s.vehicles.filter((v) => v.fuelType === 'electric');

  const monthly = useMemo(() => {
    const months = new Map<string, number>();
    for (let i = 5; i >= 0; i--) {
      const key = new Date(s.now - i * 30 * DAY).toISOString().slice(0, 7);
      months.set(key, 0);
    }
    s.fuel.forEach((f) => {
      const key = new Date(f.occurredAt).toISOString().slice(0, 7);
      if (months.has(key)) months.set(key, months.get(key)! + f.totalCost);
    });
    s.charging.forEach((c) => {
      const key = new Date(c.startedAt).toISOString().slice(0, 7);
      if (months.has(key)) months.set(key, months.get(key)! + c.totalCost);
    });
    return [...months.entries()].map(([k, v]) => ({ label: k.slice(5), value: v }));
  }, [s.fuel, s.charging, s.now]);

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Fuel & Energy</h2>
            <p className="page-sub">
              What the fleet consumes, and which vehicles convert it into distance most
              efficiently. Consumption is measured between full fills, not estimated.
            </p>
          </div>
          <select className="select" style={{ width: 150 }} value={days}
                  onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 30, 90, 180].map((d) => <option key={d} value={d}>Last {d} days</option>)}
          </select>
          <Button variant="primary" onClick={() => setRecording(true)}>
            <IconPlus size={14} /> Record fill
          </Button>
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="Fuel" value={Math.round(summary.litres).toLocaleString()} unit=" L"
               foot={`${summary.fills} fills`} />
          <Kpi label="Fuel cost" value={<Money value={summary.fuelCost} />} />
          <Kpi label="Energy" value={Math.round(summary.kwh).toLocaleString()} unit=" kWh"
               foot={`${summary.charges} sessions`} />
          <Kpi label="Energy cost" value={<Money value={summary.energyCost} />} />
          <Kpi label="Total" value={<Money value={summary.totalCost} />} tone="pulse" />
          <Kpi label="Distance" value={Math.round(summary.km).toLocaleString()} unit=" km" />
          <Kpi label="Average"
               value={summary.avgLPer100 ? summary.avgLPer100.toFixed(1) : '—'}
               unit=" L/100km" />
          <Kpi label="Cost / km"
               value={summary.costPerKm ? `€${summary.costPerKm.toFixed(3)}` : '—'} />
        </div>

        <Tabs tabs={[
          { key: 'overview', label: 'Overview' },
          { key: 'transactions', label: 'Fuel transactions', count: s.fuel.length },
          { key: 'charging', label: 'Charging', count: s.charging.length },
          { key: 'ev', label: 'EV fleet', count: evs.length },
        ]} active={tab} onChange={setTab} />

        <div style={{ paddingTop: 14 }}>
          {tab === 'overview' && (
            <div className="stack">
              <div className="grid-2">
                <Card title="Most efficient (combustion)">
                  {summary.mostEfficient.length === 0 ? (
                    <p className="muted" style={{ margin: 0 }}>
                      Not enough distance recorded in this period to rank efficiency.
                    </p>
                  ) : summary.mostEfficient.map((r) => (
                    <HBar key={r.vehicle.id}
                          label={`${r.vehicle.name} · ${r.vehicle.plate}`}
                          value={r.efficiency ?? 0}
                          max={Math.max(...summary.perVehicle.map((x) => x.efficiency ?? 0), 1)}
                          format={(v) => `${v.toFixed(1)} L/100km`}
                          tone="var(--success)" />
                  ))}
                </Card>
                <Card title="Highest consumption">
                  {summary.leastEfficient.map((r) => (
                    <HBar key={r.vehicle.id}
                          label={`${r.vehicle.name} · ${r.vehicle.plate}`}
                          value={r.efficiency ?? 0}
                          max={Math.max(...summary.perVehicle.map((x) => x.efficiency ?? 0), 1)}
                          format={(v) => `${v.toFixed(1)} L/100km`}
                          tone="var(--warning)" />
                  ))}
                </Card>
              </div>

              <Card title="Energy spend by month">
                <BarChart data={monthly} height={160}
                          format={(v) => `€${Math.round(v).toLocaleString()}`} />
              </Card>

              <Card pad={false} title="Per vehicle">
                <div className="table-wrap">
                  <table className="data">
                    <thead><tr><th>Vehicle</th><th>Energy source</th>
                               <th className="num">Distance</th><th className="num">Consumed</th>
                               <th className="num">Efficiency</th><th className="num">Cost</th>
                               <th className="num">€/km</th></tr></thead>
                    <tbody>
                      {summary.perVehicle
                        .sort((a, b) => b.totalCost - a.totalCost)
                        .map((r) => (
                          <tr key={r.vehicle.id} data-clickable="true"
                              onClick={() => app.open('vehicle', r.vehicle.id)}>
                            <td>
                              <div style={{ fontWeight: 550 }}>{r.vehicle.name}</div>
                              <div className="mono dim" style={{ fontSize: 11 }}>{r.vehicle.plate}</div>
                            </td>
                            <td>
                              <Pill tone={r.electric ? 'good' : 'neutral'}>
                                {titleCase(r.vehicle.fuelType)}
                              </Pill>
                            </td>
                            <td className="num">{r.distanceKm.toFixed(0)} km</td>
                            <td className="num">
                              {r.electric ? `${r.kwh.toFixed(1)} kWh` : `${r.litres.toFixed(1)} L`}
                            </td>
                            <td className="num">
                              {r.efficiency ? `${r.efficiency.toFixed(1)} ${r.unit}` : '—'}
                            </td>
                            <td className="num">€{r.totalCost.toFixed(0)}</td>
                            <td className="num">
                              {r.costPerKm ? `€${r.costPerKm.toFixed(3)}` : '—'}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            </div>
          )}

          {tab === 'transactions' && (
            <Card pad={false}>
              {s.fuel.length === 0 ? (
                <Empty title="No fuel recorded"
                       body="Record a fill to start tracking consumption between full tanks."
                       action={<Button variant="primary" onClick={() => setRecording(true)}>
                                 Record fill
                               </Button>} />
              ) : (
                <div className="table-wrap">
                  <table className="data">
                    <thead><tr><th>Date</th><th>Vehicle</th><th>Driver</th><th>Station</th>
                               <th className="num">Litres</th><th className="num">€/L</th>
                               <th className="num">Cost</th><th className="num">Odometer</th>
                               <th className="num">Since last</th>
                               <th className="num">L/100km</th></tr></thead>
                    <tbody>
                      {s.fuel.slice(0, 150).map((f) => (
                        <tr key={f.id}>
                          <td>{dmy(f.occurredAt)}</td>
                          <td className="mono">{store.vehicle(f.vehicleId)?.name}</td>
                          <td>{store.driver(f.driverId)?.fullName ?? '—'}</td>
                          <td>{f.stationName}</td>
                          <td className="num">{f.litres.toFixed(1)}</td>
                          <td className="num">{f.pricePerLitre.toFixed(3)}</td>
                          <td className="num">€{f.totalCost.toFixed(2)}</td>
                          <td className="num">{Math.round(f.odometerKm).toLocaleString()}</td>
                          <td className="num">
                            {f.distanceSinceLastKm ? `${f.distanceSinceLastKm.toFixed(0)} km` : '—'}
                          </td>
                          <td className="num">
                            {f.distanceSinceLastKm && f.distanceSinceLastKm > 5
                              ? ((f.litres / f.distanceSinceLastKm) * 100).toFixed(1)
                              : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          )}

          {tab === 'charging' && (
            <Card pad={false}>
              {s.charging.length === 0 ? (
                <Empty title="No charging sessions"
                       body="Charging sessions appear here once an electric vehicle plugs in." />
              ) : (
                <div className="table-wrap">
                  <table className="data">
                    <thead><tr><th>Started</th><th>Vehicle</th><th>Location</th>
                               <th className="num">Energy</th><th className="num">€/kWh</th>
                               <th className="num">Cost</th><th className="num">Charge</th>
                               <th className="num">Duration</th></tr></thead>
                    <tbody>
                      {s.charging.slice(0, 150).map((c) => (
                        <tr key={c.id}>
                          <td>{dmy(c.startedAt)}</td>
                          <td className="mono">{store.vehicle(c.vehicleId)?.name}</td>
                          <td>{c.locationName}</td>
                          <td className="num">{c.energyKwh.toFixed(1)} kWh</td>
                          <td className="num">{c.pricePerKwh.toFixed(3)}</td>
                          <td className="num">€{c.totalCost.toFixed(2)}</td>
                          <td className="num">{c.startSocPct}% → {c.endSocPct}%</td>
                          <td className="num">
                            {c.endedAt ? `${Math.round((c.endedAt - c.startedAt) / 60000)} min` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          )}

          {tab === 'ev' && (
            <div className="stack">
              <div className="kpis">
                <Kpi label="Electric vehicles" value={evs.length}
                     foot={`${((evs.length / s.vehicles.length) * 100).toFixed(0)}% of the fleet`} />
                <Kpi label="Energy used" value={Math.round(summary.kwh)} unit=" kWh" />
                <Kpi label="Energy cost" value={<Money value={summary.energyCost} />} />
                <Kpi label="Avg cost / km"
                     value={(() => {
                       const evRows = summary.perVehicle.filter((r) => r.electric && r.costPerKm);
                       if (!evRows.length) return '—';
                       return `€${(evRows.reduce((a, r) => a + (r.costPerKm ?? 0), 0) / evRows.length).toFixed(3)}`;
                     })()}
                     tone="good" />
              </div>
              <div className="grid-2">
                {evs.map((v) => {
                  const row = summary.perVehicle.find((r) => r.vehicle.id === v.id);
                  return (
                    <Card key={v.id} title={`${v.name} · ${v.plate}`}
                          actions={<Button size="sm" onClick={() => app.open('vehicle', v.id)}>
                            Open
                          </Button>}>
                      <div className="row" style={{ gap: 12, alignItems: 'center' }}>
                        <IconBattery size={26} />
                        <div className="grow">
                          <div className="row" style={{ gap: 8 }}>
                            <span className="num" style={{ fontSize: 22, fontWeight: 600 }}>
                              {Math.round(v.stateOfChargePct ?? 0)}%
                            </span>
                            <span className="dim">
                              {Math.round(v.rangeKm ?? 0)} km range
                            </span>
                          </div>
                          <div style={{ marginTop: 6 }}>
                            <div className="progress"
                                 data-tone={(v.stateOfChargePct ?? 0) < 20 ? 'danger'
                                   : (v.stateOfChargePct ?? 0) < 45 ? 'warn' : 'good'}>
                              <div style={{ width: `${v.stateOfChargePct ?? 0}%` }} />
                            </div>
                          </div>
                        </div>
                      </div>
                      <dl className="kv" style={{ marginTop: 12 }}>
                        <dt>Battery</dt><dd className="num">{v.batteryCapacityKwh} kWh</dd>
                        <dt>Distance ({days}d)</dt>
                        <dd className="num">{row?.distanceKm.toFixed(0) ?? 0} km</dd>
                        <dt>Consumption</dt>
                        <dd className="num">
                          {row?.efficiency ? `${row.efficiency.toFixed(1)} kWh/100km` : '—'}
                        </dd>
                        <dt>Cost per km</dt>
                        <dd className="num">
                          {row?.costPerKm ? `€${row.costPerKm.toFixed(3)}` : '—'}
                        </dd>
                      </dl>
                    </Card>
                  );
                })}
              </div>
              {evs.length === 0 && (
                <Empty title="No electric vehicles yet"
                       body="Sustainability suggests which vehicles fit inside practical EV range."
                       action={<Button onClick={() => app.navigate('sustainability')}>
                                 See EV candidates
                               </Button>} />
              )}
            </div>
          )}
        </div>
      </div>

      {recording && <FuelComposer onClose={() => setRecording(false)} />}
    </div>
  );
}

function FuelComposer({ onClose }: { onClose: () => void }) {
  const app = useApp();
  const { store, state: s } = app;
  const combustion = s.vehicles.filter((v) => v.fuelType !== 'electric');
  const [vehicleId, setVehicleId] = useState(combustion[0]?.id ?? '');
  const vehicle = store.vehicle(vehicleId);
  const [litres, setLitres] = useState(45);
  const [price, setPrice] = useState(s.org.settings.fuelPricePerLitre);
  const [odometer, setOdometer] = useState(Math.round(vehicle?.odometerKm ?? 0));
  const [station, setStation] = useState(
    s.places.find((p) => p.category === 'fuel_station')?.name ?? 'Neste Express');

  const previous = s.fuel.filter((f) => f.vehicleId === vehicleId)
    .sort((a, b) => b.occurredAt - a.occurredAt)[0];
  const since = previous ? odometer - previous.odometerKm : null;

  return (
    <Modal title="Record a fill" onClose={onClose}
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" disabled={!vehicleId || litres <= 0} onClick={() => {
               const ok = app.run(() => recordFuel(store, {
                 vehicleId, driverId: vehicle?.driverId, litres,
                 pricePerLitre: price, odometerKm: odometer, stationName: station,
               }), `${litres.toFixed(1)} L recorded for ${vehicle?.name}`);
               if (ok) onClose();
             }}>Record fill</Button>
           </>}>
      <div className="stack">
        <Field label="Vehicle">
          <select className="select" value={vehicleId} onChange={(e) => {
            setVehicleId(e.target.value);
            setOdometer(Math.round(store.vehicle(e.target.value)?.odometerKm ?? 0));
          }}>
            {combustion.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name} · {v.plate} · {Math.round(v.odometerKm).toLocaleString()} km
              </option>
            ))}
          </select>
        </Field>
        <Field label="Station">
          <select className="select" value={station} onChange={(e) => setStation(e.target.value)}>
            {s.places.filter((p) => p.category === 'fuel_station').map((p) => (
              <option key={p.id} value={p.name}>{p.name}</option>
            ))}
          </select>
        </Field>
        <div className="grid-2">
          <Field label="Litres">
            <input className="input" type="number" step="0.1" value={litres}
                   onChange={(e) => setLitres(Number(e.target.value))} />
          </Field>
          <Field label="Price per litre (€)">
            <input className="input" type="number" step="0.001" value={price}
                   onChange={(e) => setPrice(Number(e.target.value))} />
          </Field>
          <Field label="Odometer (km)">
            <input className="input" type="number" value={odometer}
                   onChange={(e) => setOdometer(Number(e.target.value))} />
          </Field>
        </div>
        <div className="banner" data-tone="info">
          <IconFuel size={15} />
          <span>
            Total <strong>€{(litres * price).toFixed(2)}</strong>
            {since && since > 5 && (
              <> · {since.toFixed(0)} km since the last fill ·{' '}
                {((litres / since) * 100).toFixed(1)} L/100km</>
            )}
          </span>
        </div>
        {odometer > (vehicle?.odometerKm ?? 0) && (
          <div className="banner" data-tone="warn">
            <span>
              This reading is ahead of the tracked odometer
              ({Math.round(vehicle?.odometerKm ?? 0).toLocaleString()} km).
              Recording it will move the vehicle's odometer forward and may trigger
              maintenance thresholds.
            </span>
          </div>
        )}
      </div>
    </Modal>
  );
}
