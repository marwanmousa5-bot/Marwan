// Sustainability — the fleet's emissions footprint, computed from real trips.
//
// Every number here is derived from distance actually driven and fuel actually
// burned, using the organisation's own emission factors (Settings → Emissions).
// Nothing is an industry estimate and nothing is invented.

import { useMemo, useState } from 'react';
import { sustainability } from '../../engine/selectors';
import { useApp, useEpoch } from '../app-context';
import {
  BarChart, Button, Card, Empty, HBar, Kpi, Modal, Money, Pill, Tabs, titleCase,
} from '../components/kit';
import { IconLeaf, IconBattery, IconTrendDown, IconTrendUp } from '../icons';

export function Sustainability() {
  const app = useApp();
  const epoch = useEpoch();
  const { store, state: s } = app;
  const [days, setDays] = useState(90);
  const [tab, setTab] = useState('footprint');
  const [candidate, setCandidate] = useState<string | null>(null);

  const data = useMemo(() => sustainability(store, days), [store, days, epoch]);

  const monthly = data.monthly.map((m) => ({
    label: m.month.slice(5), value: Math.round(m.co2),
  }));

  const intensity = data.monthly.map((m) => ({
    label: m.month.slice(5),
    value: m.km > 1 ? Math.round((m.co2 / m.km) * 1000) / 1000 : 0,
  }));

  // Direction of travel: the most recent month against the mean of the earlier ones.
  const trend = (() => {
    if (data.monthly.length < 2) return null;
    const last = data.monthly[data.monthly.length - 1];
    const earlier = data.monthly.slice(0, -1);
    const baseline = earlier.reduce((a, m) => a + (m.km > 1 ? m.co2 / m.km : 0), 0) /
      Math.max(1, earlier.length);
    const current = last.km > 1 ? last.co2 / last.km : 0;
    if (!baseline) return null;
    return { pct: ((current - baseline) / baseline) * 100, current, baseline };
  })();

  const totalSaving = data.candidates.reduce((a, c) => a + c.savingPerYear, 0);
  const totalCo2Saving = data.candidates.reduce((a, c) => a + c.co2SavingPerYear, 0);
  const chosen = candidate ? data.perVehicle.find((r) => r.vehicle.id === candidate) : null;

  const byFuel = useMemo(() => {
    const groups: Record<string, number> = {};
    data.perVehicle.forEach((r) => {
      groups[r.vehicle.fuelType] = (groups[r.vehicle.fuelType] ?? 0) + r.co2Kg;
    });
    return Object.entries(groups).sort((a, b) => b[1] - a[1]);
  }, [data]);

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Sustainability</h2>
            <p className="page-sub">
              CO₂ is calculated from measured fuel and energy at {s.org.settings.co2PerLitreDiesel} kg
              per litre of diesel, {s.org.settings.co2PerLitrePetrol} kg per litre of petrol and{' '}
              {s.org.settings.co2PerKwh} kg per kWh. Change those factors in Settings and every
              figure on this page moves with them.
            </p>
          </div>
          <select className="select" style={{ width: 160 }} value={days}
                  onChange={(e) => setDays(Number(e.target.value))}>
            {[30, 90, 180, 365].map((d) => <option key={d} value={d}>Last {d} days</option>)}
          </select>
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="CO₂ emitted" value={Math.round(data.totalCo2Kg).toLocaleString()} unit=" kg"
               tone="pulse" />
          <Kpi label="Emission intensity"
               value={data.co2PerKm ? data.co2PerKm.toFixed(3) : '—'} unit=" kg/km"
               foot={trend
                 ? `${trend.pct > 0 ? '+' : ''}${trend.pct.toFixed(1)}% vs earlier months`
                 : undefined}
               tone={trend ? (trend.pct > 2 ? 'danger' : trend.pct < -2 ? 'good' : undefined) : undefined} />
          <Kpi label="Per trip" value={data.co2PerTrip.toFixed(1)} unit=" kg" />
          <Kpi label="Distance" value={Math.round(data.totalKm).toLocaleString()} unit=" km" />
          <Kpi label="Electric share" value={data.evShare.toFixed(0)} unit="%" />
          <Kpi label="EV candidates" value={data.candidates.length}
               foot={data.candidates.length ? `€${Math.round(totalSaving).toLocaleString()}/yr` : undefined}
               tone={data.candidates.length ? 'good' : undefined} />
        </div>

        <Tabs active={tab} onChange={setTab} tabs={[
          { key: 'footprint', label: 'Footprint' },
          { key: 'vehicles', label: `Per vehicle (${data.perVehicle.length})` },
          { key: 'electrification', label: `Electrification (${data.candidates.length})` },
        ]} />

        {tab === 'footprint' && (
          <div className="grid-2" style={{ marginTop: 14 }}>
            <Card title="Monthly CO₂ (kg)">
              {monthly.length
                ? <BarChart data={monthly} tone="var(--good)"
                            format={(v) => `${Math.round(v).toLocaleString()} kg`} />
                : <Empty title="No trips in this window"
                         body="Widen the period or let the simulation run." />}
            </Card>
            <Card title="Emission intensity (kg CO₂ per km)">
              {intensity.length
                ? <BarChart data={intensity} tone="var(--pulse)"
                            format={(v) => `${v.toFixed(3)} kg/km`} />
                : <Empty title="Not enough distance" body="No trips recorded in this window." />}
              <p className="muted small" style={{ marginTop: 10 }}>
                Intensity is the honest measure: total CO₂ falls simply by driving less, but
                intensity only falls when the fleet gets cleaner per kilometre driven.
              </p>
            </Card>

            <Card title="Where the emissions come from">
              {byFuel.map(([fuel, kg]) => (
                <HBar key={fuel} label={titleCase(fuel)} value={Math.round(kg)}
                      max={Math.max(...byFuel.map((b) => b[1]))}
                      tone={fuel === 'electric' ? 'var(--good)' : undefined}
                      format={(v) => `${Math.round(v).toLocaleString()} kg`} />
              ))}
              <p className="muted small" style={{ marginTop: 10 }}>
                Electric vehicles are not counted as zero: their charging energy is multiplied by
                the grid factor configured for this organisation.
              </p>
            </Card>

            <Card title="Highest emitters">
              {data.perVehicle.slice(0, 6).map((r) => (
                <HBar key={r.vehicle.id} label={`${r.vehicle.name} · ${r.vehicle.plate}`}
                      value={Math.round(r.co2Kg)} max={data.perVehicle[0].co2Kg}
                      format={(v) => `${Math.round(v).toLocaleString()} kg`} />
              ))}
            </Card>
          </div>
        )}

        {tab === 'vehicles' && (
          <Card title={`Emissions by vehicle — last ${days} days`} pad={false}>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Vehicle</th><th>Fuel</th><th className="num">Trips</th>
                    <th className="num">Distance</th><th className="num">CO₂</th>
                    <th className="num">kg/km</th><th className="num">Avg day</th>
                    <th className="num">Peak day</th><th>Electrification</th>
                  </tr>
                </thead>
                <tbody>
                  {data.perVehicle.map((r) => (
                    <tr key={r.vehicle.id} className="clickable"
                        onClick={() => app.open('vehicle', r.vehicle.id)}>
                      <td>
                        <strong>{r.vehicle.name}</strong>
                        <div className="muted small">{r.vehicle.plate}</div>
                      </td>
                      <td><Pill tone={r.vehicle.fuelType === 'electric' ? 'good' : 'neutral'}>
                        {titleCase(r.vehicle.fuelType)}
                      </Pill></td>
                      <td className="num">{r.tripCount}</td>
                      <td className="num">{Math.round(r.distanceKm).toLocaleString()} km</td>
                      <td className="num">{Math.round(r.co2Kg).toLocaleString()} kg</td>
                      <td className="num">{r.co2PerKm.toFixed(3)}</td>
                      <td className="num">{Math.round(r.avgDailyKm)} km</td>
                      <td className="num">{Math.round(r.maxDailyKm)} km</td>
                      <td>
                        {r.vehicle.fuelType === 'electric'
                          ? <Pill tone="good">Already electric</Pill>
                          : r.evCandidate
                            ? <span onClick={(e) => e.stopPropagation()}>
                                <Button size="sm" onClick={() => setCandidate(r.vehicle.id)}>
                                  Review case
                                </Button>
                              </span>
                            : <span className="muted small">
                                Peak day {Math.round(r.maxDailyKm)} km exceeds the{' '}
                                {s.org.settings.evCandidateDailyKm} km threshold
                              </span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {tab === 'electrification' && (
          data.candidates.length ? (
            <>
              <Card title="Why these vehicles">
                <p className="muted" style={{ marginTop: 0 }}>
                  A vehicle qualifies when its <strong>busiest single day</strong> in the last{' '}
                  {days} days stayed under {s.org.settings.evCandidateDailyKm} km — the range a
                  comparable electric van covers without a mid-shift charge — and it has at least
                  five days of history. That is a rule, not a prediction, and you can see the
                  numbers it used in the table below.
                </p>
                <div className="kpis" style={{ marginTop: 12 }}>
                  <Kpi label="Candidates" value={data.candidates.length} tone="good" />
                  <Kpi label="Fuel cost avoided / year"
                       value={<Money value={totalSaving} />} tone="good" />
                  <Kpi label="CO₂ avoided / year"
                       value={Math.round(totalCo2Saving).toLocaleString()} unit=" kg" tone="good" />
                </div>
              </Card>
              <div className="card-grid" style={{ marginTop: 14 }}>
                {data.candidates.map((c) => (
                  <Card key={c.vehicle.id} title={`${c.vehicle.name} · ${c.vehicle.plate}`}
                        actions={<Button size="sm" onClick={() => setCandidate(c.vehicle.id)}>
                          Full case
                        </Button>}>
                    <dl className="dl">
                      <dt>Peak day</dt>
                      <dd className="num">{Math.round(c.maxDailyKm)} km</dd>
                      <dt>Average day</dt>
                      <dd className="num">{Math.round(c.avgDailyKm)} km</dd>
                      <dt>Fuel today</dt>
                      <dd className="num"><Money value={c.fuelCost} /></dd>
                      <dt>Energy instead</dt>
                      <dd className="num"><Money value={c.evCost} /></dd>
                      <dt>Saving / year</dt>
                      <dd className="num good">
                        <IconTrendDown size={12} /> <Money value={c.savingPerYear} />
                      </dd>
                      <dt>CO₂ / year</dt>
                      <dd className="num good">
                        −{Math.round(c.co2SavingPerYear).toLocaleString()} kg
                      </dd>
                    </dl>
                  </Card>
                ))}
              </div>
            </>
          ) : (
            <Empty title="No electrification candidates"
                   body={`Every combustion vehicle exceeded ${s.org.settings.evCandidateDailyKm} km on at least one day in this window, so none of them would finish a shift on a single charge.`} />
          )
        )}

        {chosen && (
          <Modal title={`Electrification case — ${chosen.vehicle.name}`}
                 subtitle={`${chosen.vehicle.plate} · ${chosen.vehicle.make} ${chosen.vehicle.model} (${chosen.vehicle.year})`}
                 onClose={() => setCandidate(null)}
                 footer={<>
                   <Button onClick={() => setCandidate(null)}>Close</Button>
                   <Button variant="primary" onClick={() => {
                     setCandidate(null);
                     app.open('vehicle', chosen.vehicle.id);
                   }}>Open vehicle</Button>
                 </>}>
            <div className="banner info" style={{ marginBottom: 14 }}>
              <IconLeaf size={16} />
              <div>
                This is a comparison of measured costs, not a purchase recommendation. It uses this
                vehicle's own last {days} days of distance, priced at the organisation's fuel and
                electricity rates. It does not include the purchase price of a replacement, charger
                installation, or residual value — add those before making the decision.
              </div>
            </div>

            <div className="grid-2">
              <Card title="What this vehicle did">
                <dl className="dl">
                  <dt>Trips</dt><dd className="num">{chosen.tripCount}</dd>
                  <dt>Distance</dt>
                  <dd className="num">{Math.round(chosen.distanceKm).toLocaleString()} km</dd>
                  <dt>Average day</dt><dd className="num">{Math.round(chosen.avgDailyKm)} km</dd>
                  <dt>Busiest day</dt><dd className="num">{Math.round(chosen.maxDailyKm)} km</dd>
                  <dt>Range threshold</dt>
                  <dd className="num">{s.org.settings.evCandidateDailyKm} km</dd>
                </dl>
              </Card>
              <Card title="What it would cost">
                <dl className="dl">
                  <dt>Fuel, this window</dt><dd className="num"><Money value={chosen.fuelCost} /></dd>
                  <dt>Energy instead</dt><dd className="num"><Money value={chosen.evCost} /></dd>
                  <dt>Difference / year</dt>
                  <dd className="num good"><Money value={chosen.savingPerYear} /></dd>
                  <dt>CO₂ now</dt>
                  <dd className="num">{Math.round(chosen.co2Kg).toLocaleString()} kg</dd>
                  <dt>CO₂ electric</dt>
                  <dd className="num">{Math.round(chosen.evCo2Kg).toLocaleString()} kg</dd>
                  <dt>CO₂ / year</dt>
                  <dd className="num good">
                    −{Math.round(chosen.co2SavingPerYear).toLocaleString()} kg
                  </dd>
                </dl>
              </Card>
            </div>

            <Card title="Headroom on the busiest day">
              <HBar label="Busiest day" value={Math.round(chosen.maxDailyKm)}
                    max={s.org.settings.evCandidateDailyKm}
                    tone={chosen.maxDailyKm > s.org.settings.evCandidateDailyKm * 0.85
                      ? 'var(--warn)' : 'var(--good)'}
                    format={(v) => `${Math.round(v)} km of ${s.org.settings.evCandidateDailyKm} km`} />
              <p className="muted small" style={{ marginTop: 8 }}>
                {chosen.maxDailyKm > s.org.settings.evCandidateDailyKm * 0.85
                  ? <><IconTrendUp size={12} /> Headroom is thin. A cold Helsinki winter reduces
                      usable range, so plan a depot charger before switching this one.</>
                  : <><IconBattery size={12} /> Comfortable headroom — overnight depot charging
                      would cover every day in this window.</>}
              </p>
            </Card>
          </Modal>
        )}
      </div>
    </div>
  );
}
