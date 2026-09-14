// Costs & TCO — what the fleet actually costs, per vehicle and per kilometre.

import { useMemo, useState } from 'react';
import { annualDepreciation, bookValue } from '../../engine/derive';
import { costSummary } from '../../engine/selectors';
import { useApp, useEpoch } from '../app-context';
import {
  BarChart, Card, Donut, HBar, Kpi, Money, Pill, Tabs, titleCase,
} from '../components/kit';
import { IconCoin } from '../icons';

const CATEGORY_COLOURS: Record<string, string> = {
  fuel: '#1E90FF', energy: '#2ECC71', maintenance: '#9B6BFF', insurance: '#F5A623',
  registration: '#5D7FF0', depreciation: '#7E8C9E', tolls: '#2FB8D9',
  fines: '#E74C3C', other: '#FF6B35',
};

export function Costs() {
  const app = useApp();
  const epoch = useEpoch();
  const { store, state: s } = app;
  const [months, setMonths] = useState(12);
  const [tab, setTab] = useState('fleet');

  const fleet = useMemo(() => costSummary(store, months), [store, months, epoch]);
  const perVehicle = useMemo(() => s.vehicles.map((v) => {
    const c = costSummary(store, months, v.id);
    return { vehicle: v, ...c };
  }).sort((a, b) => b.operating - a.operating), [store, months, epoch]);

  const donut = Object.entries(fleet.byCategory)
    .sort((a, b) => b[1] - a[1])
    .map(([label, value]) => ({
      label: titleCase(label), value,
      color: CATEGORY_COLOURS[label] ?? '#7E8C9E',
    }));

  const trend = fleet.trend.map((t) => ({
    label: String(t.month).slice(5), value: t.total as number,
  }));

  const lifecycleGroups = useMemo(() => {
    const groups: Record<string, { count: number; value: number; book: number }> = {};
    s.vehicles.forEach((v) => {
      const g = groups[v.lifecycle] ?? { count: 0, value: 0, book: 0 };
      g.count++;
      g.value += v.purchaseValue;
      g.book += bookValue(v, s.now);
      groups[v.lifecycle] = g;
    });
    return groups;
  }, [s.vehicles, s.now]);

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Costs & TCO</h2>
            <p className="page-sub">
              Total cost of ownership is acquisition plus operating cost minus the
              vehicle's remaining book value, using straight-line depreciation.
            </p>
          </div>
          <select className="select" style={{ width: 160 }} value={months}
                  onChange={(e) => setMonths(Number(e.target.value))}>
            {[3, 6, 12, 24].map((m) => <option key={m} value={m}>Last {m} months</option>)}
          </select>
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="Operating cost" value={<Money value={fleet.operating} />} tone="pulse" />
          <Kpi label="Cost per km"
               value={fleet.costPerKm ? `€${fleet.costPerKm.toFixed(2)}` : '—'} />
          <Kpi label="Cost per day" value={<Money value={fleet.costPerDay} />} />
          <Kpi label="Distance" value={Math.round(fleet.distanceKm).toLocaleString()} unit=" km" />
          <Kpi label="Fleet acquisition" value={<Money value={fleet.acquisition} />} />
          <Kpi label="Book value" value={<Money value={fleet.bookValue} />} />
          <Kpi label="Fleet TCO" value={<Money value={fleet.tco} />} />
        </div>

        <Tabs tabs={[
          { key: 'fleet', label: 'Fleet' },
          { key: 'vehicles', label: 'By vehicle', count: s.vehicles.length },
          { key: 'category', label: 'By category' },
          { key: 'lifecycle', label: 'Asset lifecycle' },
        ]} active={tab} onChange={setTab} />

        <div style={{ paddingTop: 14 }}>
          {tab === 'fleet' && (
            <div className="stack">
              <div className="grid-2">
                <Card title="Where the money goes">
                  <Donut segments={donut} size={150}
                         centerValue={`€${Math.round(fleet.operating / 1000)}k`}
                         centerLabel={`${months} months`} />
                </Card>
                <Card title="Monthly operating cost">
                  <BarChart data={trend} height={170}
                            format={(v) => `€${Math.round(v / 1000)}k`} />
                </Card>
              </div>
              <Card title="Cost per kilometre, by vehicle">
                {perVehicle.filter((r) => r.costPerKm).slice(0, 12).map((r) => (
                  <HBar key={r.vehicle.id}
                        label={`${r.vehicle.name} · ${r.vehicle.plate}`}
                        value={r.costPerKm ?? 0}
                        max={Math.max(...perVehicle.map((x) => x.costPerKm ?? 0))}
                        format={(v) => `€${v.toFixed(2)}/km`}
                        tone={r.vehicle.fuelType === 'electric'
                          ? 'var(--success)' : 'var(--pulse)'} />
                ))}
              </Card>
            </div>
          )}

          {tab === 'vehicles' && (
            <Card pad={false}>
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>Vehicle</th><th>Energy</th><th className="num">Distance</th>
                             <th className="num">Fuel/energy</th><th className="num">Maintenance</th>
                             <th className="num">Fixed</th><th className="num">Depreciation</th>
                             <th className="num">Operating</th><th className="num">€/km</th>
                             <th className="num">Book value</th><th className="num">TCO</th></tr></thead>
                  <tbody>
                    {perVehicle.map((r) => {
                      const c = r.byCategory;
                      const energy = (c.fuel ?? 0) + (c.energy ?? 0);
                      const fixed = (c.insurance ?? 0) + (c.registration ?? 0) + (c.other ?? 0);
                      return (
                        <tr key={r.vehicle.id} data-clickable="true"
                            onClick={() => app.open('vehicle', r.vehicle.id)}>
                          <td>
                            <div style={{ fontWeight: 550 }}>{r.vehicle.name}</div>
                            <div className="mono dim" style={{ fontSize: 11 }}>{r.vehicle.plate}</div>
                          </td>
                          <td><Pill tone={r.vehicle.fuelType === 'electric' ? 'good' : 'neutral'}>
                            {titleCase(r.vehicle.fuelType)}</Pill></td>
                          <td className="num">{Math.round(r.distanceKm).toLocaleString()}</td>
                          <td className="num">€{Math.round(energy).toLocaleString()}</td>
                          <td className="num">€{Math.round(c.maintenance ?? 0).toLocaleString()}</td>
                          <td className="num">€{Math.round(fixed).toLocaleString()}</td>
                          <td className="num">€{Math.round(c.depreciation ?? 0).toLocaleString()}</td>
                          <td className="num" style={{ fontWeight: 600 }}>
                            €{Math.round(r.operating).toLocaleString()}
                          </td>
                          <td className="num">
                            {r.costPerKm ? `€${r.costPerKm.toFixed(2)}` : '—'}
                          </td>
                          <td className="num">
                            €{Math.round(bookValue(r.vehicle, s.now)).toLocaleString()}
                          </td>
                          <td className="num">€{Math.round(r.tco).toLocaleString()}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {tab === 'category' && (
            <div className="stack">
              <Card title={`Spend by category, last ${months} months`}>
                {Object.entries(fleet.byCategory)
                  .sort((a, b) => b[1] - a[1])
                  .map(([cat, amount]) => (
                    <HBar key={cat} label={titleCase(cat)} value={amount}
                          max={Math.max(...Object.values(fleet.byCategory))}
                          format={(v) => `€${Math.round(v).toLocaleString()}`}
                          tone={CATEGORY_COLOURS[cat]} />
                  ))}
              </Card>
              <Card pad={false} title="Recent cost records">
                <div className="table-wrap">
                  <table className="data">
                    <thead><tr><th>Date</th><th>Vehicle</th><th>Category</th>
                               <th>Description</th><th className="num">Amount</th></tr></thead>
                    <tbody>
                      {[...s.costs]
                        .sort((a, b) => b.incurredOn.localeCompare(a.incurredOn))
                        .slice(0, 80)
                        .map((c) => (
                          <tr key={c.id}>
                            <td className="num">{c.incurredOn}</td>
                            <td className="mono">{store.vehicle(c.vehicleId)?.name ?? '—'}</td>
                            <td>
                              <span className="row" style={{ gap: 6 }}>
                                <i style={{ width: 8, height: 8, borderRadius: 2,
                                            background: CATEGORY_COLOURS[c.category] ?? '#888' }} />
                                {titleCase(c.category)}
                              </span>
                            </td>
                            <td className="truncate" style={{ maxWidth: 300 }}>{c.description}</td>
                            <td className="num">€{c.amount.toFixed(2)}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            </div>
          )}

          {tab === 'lifecycle' && (
            <div className="stack">
              <div className="kpis">
                {Object.entries(lifecycleGroups).map(([state, g]) => (
                  <Kpi key={state} label={titleCase(state)} value={g.count}
                       foot={`€${Math.round(g.book / 1000)}k book value`} />
                ))}
              </div>
              <Card pad={false} title="Asset register">
                <div className="table-wrap">
                  <table className="data">
                    <thead><tr><th>Vehicle</th><th>Lifecycle</th><th>Ownership</th>
                               <th className="num">Purchased</th><th className="num">Purchase value</th>
                               <th className="num">Book value</th><th className="num">Depreciation/yr</th>
                               <th className="num">Lifetime km</th>
                               <th>Replacement</th></tr></thead>
                    <tbody>
                      {s.vehicles.map((v) => {
                        const book = bookValue(v, s.now);
                        const ageYears = (s.now - Date.parse(v.purchaseDate)) / (365.25 * 86400000);
                        const replace = v.odometerKm > 250000 || ageYears > 8 ||
                          book <= v.residualValue * 1.05;
                        return (
                          <tr key={v.id} data-clickable="true"
                              onClick={() => app.open('vehicle', v.id)}>
                            <td>
                              <div style={{ fontWeight: 550 }}>{v.name}</div>
                              <div className="mono dim" style={{ fontSize: 11 }}>{v.plate}</div>
                            </td>
                            <td><Pill tone={v.lifecycle === 'active' ? 'good'
                              : v.lifecycle === 'retired' ? 'neutral' : 'warn'}>
                              {titleCase(v.lifecycle)}</Pill></td>
                            <td>{titleCase(v.ownership)}</td>
                            <td className="num">{v.purchaseDate}</td>
                            <td className="num">€{v.purchaseValue.toLocaleString()}</td>
                            <td className="num">€{Math.round(book).toLocaleString()}</td>
                            <td className="num">€{Math.round(annualDepreciation(v)).toLocaleString()}</td>
                            <td className="num">{Math.round(v.odometerKm).toLocaleString()}</td>
                            <td>
                              {replace
                                ? <Pill tone="warn">Consider replacing</Pill>
                                : <span className="dim">Keep</span>}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>
              <div className="banner" data-tone="info">
                <IconCoin size={15} />
                <span>
                  Replacement is flagged when a vehicle passes 250,000 km, is over eight
                  years old, or has depreciated to within 5% of its residual value.
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
