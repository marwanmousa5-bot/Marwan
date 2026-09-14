// Compliance & Documents — an expiry workspace, sorted by what lapses first.

import { useEffect, useMemo, useState } from 'react';
import { createDocument, renewDocument, scanCompliance } from '../../engine/actions';
import { documentStatus } from '../../engine/derive';
import { complianceSummary } from '../../engine/selectors';
import type { FleetDocument } from '../../engine/types';
import { useApp, useEpoch } from '../app-context';
import {
  Button, Card, Empty, Field, Kpi, Modal, Money, Pill, Progress, Tabs, titleCase,
} from '../components/kit';
import { IconAlert, IconDoc, IconPlus, IconRefresh } from '../icons';

const DAY = 86400000;

export function Compliance() {
  const app = useApp();
  const epoch = useEpoch();
  const { store, state: s } = app;
  const [tab, setTab] = useState('documents');
  const [statusFilter, setStatusFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [query, setQuery] = useState('');
  const [openId, setOpenId] = useState<string | undefined>(app.params.document);
  const [adding, setAdding] = useState(false);

  useEffect(() => { if (app.params.document) setOpenId(app.params.document); },
            [app.params.document]);

  const summary = useMemo(() => complianceSummary(store), [store, epoch]);
  const warn = Math.max(...s.org.settings.documentAlertDays);

  const docs = useMemo(() => s.documents
    .map((d) => ({ doc: d, days: Math.round((Date.parse(d.expiryDate) - s.now) / DAY) }))
    .filter(({ doc }) => {
      const st = documentStatus(doc.expiryDate, s.now, warn);
      if (statusFilter && st !== statusFilter) return false;
      if (typeFilter && doc.kind !== typeFilter) return false;
      const q = query.trim().toLowerCase();
      if (q && ![doc.name, doc.reference, doc.issuer].some((f) => f?.toLowerCase().includes(q))) {
        return false;
      }
      return true;
    })
    .sort((a, b) => a.days - b.days), [s.documents, s.now, statusFilter, typeFilter, query, warn]);

  const openDoc = openId ? s.documents.find((d) => d.id === openId) : undefined;

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Compliance & Documents</h2>
            <p className="page-sub">
              What the fleet is at risk of. Reminders fire at{' '}
              {s.org.settings.documentAlertDays.join(', ')} days before expiry, and again
              the day a document lapses.
            </p>
          </div>
          <Button onClick={() => {
            const res = app.run(() => scanCompliance(store));
            if (res) {
              app.toast(res.raised ? 'info' : 'success',
                res.raised
                  ? `${res.raised} reminder${res.raised === 1 ? '' : 's'} raised across ${res.checked} documents`
                  : `${res.checked} documents checked — nothing new to flag`);
            }
          }}><IconRefresh size={14} /> Run expiry scan</Button>
          <Button variant="primary" onClick={() => setAdding(true)}>
            <IconPlus size={14} /> Add document
          </Button>
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="Documents" value={summary.total} />
          <Kpi label="Valid" value={summary.valid} tone="good"
               active={statusFilter === 'valid'}
               onClick={() => setStatusFilter(statusFilter === 'valid' ? '' : 'valid')} />
          <Kpi label="Expiring soon" value={summary.expiring_soon}
               tone={summary.expiring_soon ? 'warn' : undefined}
               active={statusFilter === 'expiring_soon'}
               onClick={() => setStatusFilter(statusFilter === 'expiring_soon' ? '' : 'expiring_soon')} />
          <Kpi label="Expired" value={summary.expired}
               tone={summary.expired ? 'danger' : undefined}
               active={statusFilter === 'expired'}
               onClick={() => setStatusFilter(statusFilter === 'expired' ? '' : 'expired')} />
          <Kpi label="Within 7 days" value={summary.horizon.within_7_days}
               tone={summary.horizon.within_7_days ? 'danger' : undefined} />
          <Kpi label="Compliance rate" value={summary.complianceRate} unit="%"
               tone={summary.complianceRate >= 95 ? 'good' : 'warn'} />
        </div>

        <Tabs tabs={[
          { key: 'documents', label: 'Documents', count: s.documents.length },
          { key: 'licences', label: 'Driver licences', count: s.drivers.length },
          { key: 'horizon', label: 'Renewal horizon' },
        ]} active={tab} onChange={setTab} />

        <div style={{ paddingTop: 14 }}>
          {tab === 'documents' && (
            <>
              <div className="row wrap" style={{ gap: 8, marginBottom: 12 }}>
                <input className="input" placeholder="Search name, reference or issuer"
                       value={query} onChange={(e) => setQuery(e.target.value)}
                       style={{ maxWidth: 280 }} />
                <select className="select" style={{ width: 170 }} value={typeFilter}
                        onChange={(e) => setTypeFilter(e.target.value)}>
                  <option value="">All types</option>
                  {['registration', 'insurance', 'inspection', 'driver_license',
                    'permit', 'certification', 'other'].map((t) =>
                    <option key={t} value={t}>{titleCase(t)}</option>)}
                </select>
                <div className="grow" />
                <span className="dim" style={{ fontSize: 12 }}>{docs.length} documents</span>
              </div>

              <Card pad={false}>
                {docs.length === 0 ? (
                  <Empty title="No documents match" body="Clear a filter to see the rest." />
                ) : (
                  <div className="table-wrap">
                    <table className="data">
                      <thead><tr><th>Document</th><th>Type</th><th>Applies to</th>
                                 <th>Issuer</th><th>Reference</th><th>Expires</th>
                                 <th className="num">Days left</th><th>Status</th>
                                 <th className="num">Cost</th><th></th></tr></thead>
                      <tbody>
                        {docs.map(({ doc, days }) => {
                          const st = documentStatus(doc.expiryDate, s.now, warn);
                          const subject = doc.vehicleId
                            ? store.vehicle(doc.vehicleId)
                            : doc.driverId ? store.driver(doc.driverId) : null;
                          return (
                            <tr key={doc.id} data-clickable="true" onClick={() => setOpenId(doc.id)}>
                              <td style={{ fontWeight: 550 }}>{doc.name}</td>
                              <td>{titleCase(doc.kind)}</td>
                              <td>
                                {subject
                                  ? ('plate' in subject
                                      ? `${subject.name} · ${subject.plate}`
                                      : subject.fullName)
                                  : <span className="dim">Organization</span>}
                              </td>
                              <td className="truncate" style={{ maxWidth: 150 }}>{doc.issuer}</td>
                              <td className="mono" style={{ fontSize: 11 }}>{doc.reference}</td>
                              <td className="num">{doc.expiryDate}</td>
                              <td className="num" style={{
                                color: days < 0 ? 'var(--danger)'
                                  : days <= 7 ? 'var(--warning)' : undefined,
                              }}>{days < 0 ? `${Math.abs(days)} over` : days}</td>
                              <td><Pill tone={st === 'valid' ? 'good'
                                : st === 'expired' ? 'danger' : 'warn'}>
                                {titleCase(st)}</Pill></td>
                              <td className="num">{doc.cost ? `€${doc.cost}` : '—'}</td>
                              <td onClick={(e) => e.stopPropagation()}>
                                <Button size="sm" onClick={() => setOpenId(doc.id)}>Renew</Button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            </>
          )}

          {tab === 'licences' && (
            <Card pad={false}>
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>Driver</th><th>Class</th><th>Number</th><th>Expires</th>
                             <th className="num">Days left</th><th>Status</th></tr></thead>
                  <tbody>
                    {[...s.drivers]
                      .sort((a, b) => a.licenseExpiry.localeCompare(b.licenseExpiry))
                      .map((d) => {
                        const st = documentStatus(d.licenseExpiry, s.now, warn);
                        const days = Math.round((Date.parse(d.licenseExpiry) - s.now) / DAY);
                        return (
                          <tr key={d.id} data-clickable="true" onClick={() => app.open('driver', d.id)}>
                            <td style={{ fontWeight: 550 }}>{d.fullName}</td>
                            <td className="mono">{d.licenseClass}</td>
                            <td className="mono" style={{ fontSize: 11 }}>{d.licenseNumber}</td>
                            <td className="num">{d.licenseExpiry}</td>
                            <td className="num" style={{
                              color: days < 0 ? 'var(--danger)' : days <= 30 ? 'var(--warning)' : undefined,
                            }}>{days < 0 ? `${Math.abs(days)} over` : days}</td>
                            <td><Pill tone={st === 'valid' ? 'good'
                              : st === 'expired' ? 'danger' : 'warn'}>{titleCase(st)}</Pill></td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {tab === 'horizon' && (
            <div className="stack">
              <Card title="What lapses when">
                {[
                  { label: 'Already expired', count: summary.expired, tone: 'danger' as const },
                  { label: 'Within 7 days', count: summary.horizon.within_7_days, tone: 'danger' as const },
                  { label: 'Within 14 days', count: summary.horizon.within_14_days, tone: 'warn' as const },
                  { label: 'Within 30 days', count: summary.horizon.within_30_days, tone: 'warn' as const },
                  { label: 'Within 90 days', count: summary.horizon.within_90_days, tone: 'good' as const },
                ].map((row) => (
                  <div key={row.label} style={{ marginBottom: 10 }}>
                    <div className="row" style={{ fontSize: 12.5, marginBottom: 4 }}>
                      <span className="grow">{row.label}</span>
                      <span className="mono">{row.count}</span>
                    </div>
                    <Progress pct={(row.count / Math.max(1, summary.total)) * 100} tone={row.tone} />
                  </div>
                ))}
              </Card>
              <Card pad={false} title="Next twelve renewals">
                <div className="table-wrap">
                  <table className="data">
                    <thead><tr><th>Document</th><th>Applies to</th><th>Expires</th>
                               <th className="num">Days</th><th className="num">Cost</th></tr></thead>
                    <tbody>
                      {s.documents
                        .map((d) => ({ d, days: Math.round((Date.parse(d.expiryDate) - s.now) / DAY) }))
                        .sort((a, b) => a.days - b.days)
                        .slice(0, 12)
                        .map(({ d, days }) => {
                          const subject = d.vehicleId ? store.vehicle(d.vehicleId)
                            : d.driverId ? store.driver(d.driverId) : null;
                          return (
                            <tr key={d.id} data-clickable="true" onClick={() => setOpenId(d.id)}>
                              <td>{d.name}</td>
                              <td>{subject ? ('plate' in subject ? subject.name : subject.fullName)
                                : 'Organization'}</td>
                              <td className="num">{d.expiryDate}</td>
                              <td className="num">{days}</td>
                              <td className="num">{d.cost ? `€${d.cost}` : '—'}</td>
                            </tr>
                          );
                        })}
                    </tbody>
                  </table>
                </div>
              </Card>
            </div>
          )}
        </div>
      </div>

      {openDoc && <DocumentDetail doc={openDoc} onClose={() => setOpenId(undefined)} />}
      {adding && <AddDocument onClose={() => setAdding(false)} />}
    </div>
  );
}

function DocumentDetail({ doc, onClose }: { doc: FleetDocument; onClose: () => void }) {
  const app = useApp();
  const { store, state: s } = app;
  const days = Math.round((Date.parse(doc.expiryDate) - s.now) / DAY);
  const subject = doc.vehicleId ? store.vehicle(doc.vehicleId)
    : doc.driverId ? store.driver(doc.driverId) : null;
  const [renewing, setRenewing] = useState(false);
  const [newExpiry, setNewExpiry] = useState(
    new Date(Date.parse(doc.expiryDate) + 365 * DAY).toISOString().slice(0, 10));
  const [cost, setCost] = useState(doc.cost ?? 0);

  return (
    <Modal title={doc.name} onClose={onClose}
           subtitle={
             <div className="row wrap" style={{ gap: 7 }}>
               <Pill tone={doc.status === 'valid' ? 'good'
                 : doc.status === 'expired' ? 'danger' : 'warn'}>{titleCase(doc.status)}</Pill>
               <span className="dim">{titleCase(doc.kind)}</span>
               {subject && (
                 <button style={{ color: 'var(--pulse)' }} onClick={() => {
                   if (doc.vehicleId) app.open('vehicle', doc.vehicleId);
                   else if (doc.driverId) app.open('driver', doc.driverId);
                   onClose();
                 }}>
                   {'plate' in subject ? `${subject.name} · ${subject.plate}` : subject.fullName}
                 </button>
               )}
             </div>
           }
           footer={<>
             <Button onClick={onClose}>Close</Button>
             <div className="grow" />
             <Button variant="primary" onClick={() => setRenewing(true)}>Renew document</Button>
           </>}>
      <div className="stack">
        {days < 0 && (
          <div className="banner" data-tone="danger">
            <IconAlert size={15} />
            <span>
              <strong>Expired {Math.abs(days)} day{Math.abs(days) === 1 ? '' : 's'} ago.</strong>{' '}
              {doc.vehicleId ? 'This vehicle should be taken out of service until it is renewed.'
                : 'This driver should not be assigned work until it is renewed.'}
            </span>
          </div>
        )}
        {days >= 0 && days <= 30 && (
          <div className="banner" data-tone="warn">
            <IconAlert size={15} />
            <span>Expires in {days} day{days === 1 ? '' : 's'}. Renew before it lapses.</span>
          </div>
        )}
        <Card title="Details">
          <dl className="kv">
            <dt>Type</dt><dd>{titleCase(doc.kind)}</dd>
            <dt>Issuer</dt><dd>{doc.issuer}</dd>
            <dt>Reference</dt><dd className="mono">{doc.reference}</dd>
            <dt>Issued</dt><dd className="num">{doc.issueDate}</dd>
            <dt>Expires</dt><dd className="num">{doc.expiryDate}</dd>
            <dt>Days remaining</dt>
            <dd className="num">{days < 0 ? `${Math.abs(days)} overdue` : days}</dd>
            {doc.cost != null && <><dt>Cost</dt><dd><Money value={doc.cost} /></dd></>}
            {doc.notes && <><dt>Notes</dt><dd>{doc.notes}</dd></>}
          </dl>
        </Card>
      </div>

      {renewing && (
        <Modal title={`Renew ${doc.name}`} onClose={() => setRenewing(false)}
               footer={<>
                 <Button onClick={() => setRenewing(false)}>Cancel</Button>
                 <Button variant="primary" onClick={() => {
                   const ok = app.run(
                     () => renewDocument(store, doc.id, newExpiry, cost || undefined),
                     `${doc.name} renewed until ${newExpiry}`);
                   if (ok) { setRenewing(false); onClose(); }
                 }}>Confirm renewal</Button>
               </>}>
          <div className="stack">
            <Field label="New expiry date">
              <input className="input" type="date" value={newExpiry}
                     onChange={(e) => setNewExpiry(e.target.value)} />
            </Field>
            <Field label="Renewal cost (€)" hint="Recorded against the vehicle's cost history.">
              <input className="input" type="number" value={cost}
                     onChange={(e) => setCost(Number(e.target.value))} />
            </Field>
            <div className="banner" data-tone="info">
              <IconDoc size={15} />
              <span>
                Renewing clears the reminder ladder and resolves any open compliance
                alert for this document.
              </span>
            </div>
          </div>
        </Modal>
      )}
    </Modal>
  );
}

function AddDocument({ onClose }: { onClose: () => void }) {
  const app = useApp();
  const { state: s } = app;
  const [kind, setKind] = useState('registration');
  const [name, setName] = useState('');
  const [entity, setEntity] = useState<'vehicle' | 'driver' | 'organization'>('vehicle');
  const [vehicleId, setVehicleId] = useState(s.vehicles[0]?.id ?? '');
  const [driverId, setDriverId] = useState(s.drivers[0]?.id ?? '');
  const [issuer, setIssuer] = useState('Traficom');
  const [reference, setReference] = useState('');
  const [expiry, setExpiry] = useState(
    new Date(s.now + 365 * DAY).toISOString().slice(0, 10));
  const [cost, setCost] = useState(0);

  return (
    <Modal title="Add a document" onClose={onClose}
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" disabled={!name.trim()} onClick={() => {
               const ok = app.run(() => createDocument(app.store, {
                 kind, name, entityType: entity,
                 vehicleId: entity === 'vehicle' ? vehicleId : undefined,
                 driverId: entity === 'driver' ? driverId : undefined,
                 issuer, reference: reference || '—',
                 issueDate: new Date(s.now).toISOString().slice(0, 10),
                 expiryDate: expiry, cost: cost || undefined,
               }), `${name} added`);
               if (ok) onClose();
             }}>Add document</Button>
           </>}>
      <div className="stack">
        <div className="grid-2">
          <Field label="Type">
            <select className="select" value={kind} onChange={(e) => setKind(e.target.value)}>
              {['registration', 'insurance', 'inspection', 'driver_license',
                'permit', 'certification', 'other'].map((t) =>
                <option key={t} value={t}>{titleCase(t)}</option>)}
            </select>
          </Field>
          <Field label="Applies to">
            <select className="select" value={entity}
                    onChange={(e) => setEntity(e.target.value as typeof entity)}>
              <option value="vehicle">A vehicle</option>
              <option value="driver">A driver</option>
              <option value="organization">The organization</option>
            </select>
          </Field>
        </div>
        {entity === 'vehicle' && (
          <Field label="Vehicle">
            <select className="select" value={vehicleId}
                    onChange={(e) => setVehicleId(e.target.value)}>
              {s.vehicles.map((v) => (
                <option key={v.id} value={v.id}>{v.name} · {v.plate}</option>
              ))}
            </select>
          </Field>
        )}
        {entity === 'driver' && (
          <Field label="Driver">
            <select className="select" value={driverId}
                    onChange={(e) => setDriverId(e.target.value)}>
              {s.drivers.map((d) => <option key={d.id} value={d.id}>{d.fullName}</option>)}
            </select>
          </Field>
        )}
        <Field label="Name">
          <input className="input" value={name} onChange={(e) => setName(e.target.value)}
                 placeholder="Motor insurance — ABC-123" />
        </Field>
        <div className="grid-2">
          <Field label="Issuer">
            <input className="input" value={issuer} onChange={(e) => setIssuer(e.target.value)} />
          </Field>
          <Field label="Reference">
            <input className="input" value={reference}
                   onChange={(e) => setReference(e.target.value)} />
          </Field>
          <Field label="Expiry date">
            <input className="input" type="date" value={expiry}
                   onChange={(e) => setExpiry(e.target.value)} />
          </Field>
          <Field label="Cost (€)">
            <input className="input" type="number" value={cost}
                   onChange={(e) => setCost(Number(e.target.value))} />
          </Field>
        </div>
      </div>
    </Modal>
  );
}
