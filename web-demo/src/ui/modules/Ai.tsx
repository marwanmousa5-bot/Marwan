// AI Fleet Intelligence.
//
// Three honest things and no fourth: proactive recommendations derived from the
// organisation's own data, a question box that answers from that same data, and
// anomaly detection against each subject's own baseline. Nothing here changes
// state on its own — every action is a proposal a person confirms (spec 45).

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  SUGGESTED_QUESTIONS, anomalies, applyProposal, applyRecommendation,
  ask, dismissRecommendation, generateRecommendations, periodReport,
} from '../../engine/intelligence';
import type { AssistantAnswer } from '../../engine/intelligence';
import { useApp, useEpoch } from '../app-context';
import {
  Button, Card, Confirm, Empty, Kpi, Modal, Pill, Tabs, relTime, titleCase,
} from '../components/kit';
import { IconRefresh, IconSpark, IconCheck, IconClose, IconChart } from '../icons';

interface Turn {
  id: number;
  question: string;
  answer: AssistantAnswer;
  at: number;
  outcome?: string;
}

export function Ai() {
  const app = useApp();
  const epoch = useEpoch();
  const { store, state: s } = app;
  const [tab, setTab] = useState('copilot');
  const [question, setQuestion] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [confirming, setConfirming] = useState<{ recId?: string; turnId?: number } | null>(null);
  const [dismissing, setDismissing] = useState<string | null>(null);
  const [report, setReport] = useState<7 | 30 | null>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const turnSeq = useRef(1);

  const pending = s.recommendations.filter((r) => r.status === 'pending');
  const handled = s.recommendations.filter((r) => r.status !== 'pending');
  const detected = useMemo(
    () => anomalies(store),
    [store, epoch]);

  // Scan once when the page opens so the copilot is never empty on arrival.
  useEffect(() => {
    const made = generateRecommendations(store);
    if (made.length) store.emit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: 'smooth' });
  }, [turns]);

  const submit = (text: string) => {
    const q = text.trim();
    if (!q) return;
    const answer = ask(store, q);
    setTurns((prev) => [...prev, { id: turnSeq.current++, question: q, answer, at: s.now }]);
    setQuestion('');
  };

  const confirmingRec = confirming?.recId
    ? s.recommendations.find((r) => r.id === confirming.recId) : null;
  const confirmingTurn = confirming?.turnId
    ? turns.find((t) => t.id === confirming.turnId) : null;

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Fleet Intelligence</h2>
            <p className="page-sub">
              Rule-based analysis over this organisation's own records. It proposes; you decide.
              Every recommendation shows the evidence it used, and applying one runs exactly the
              same action the corresponding module would.
            </p>
          </div>
          <Button onClick={() => app.run(() => {
            const made = generateRecommendations(store);
            store.emit();
            return made;
          }, 'Scan complete')}>
            <IconRefresh size={14} /> Re-scan now
          </Button>
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="Open recommendations" value={pending.length}
               tone={pending.length ? 'pulse' : undefined} />
          <Kpi label="Anomalies detected" value={detected.length}
               tone={detected.filter((a) => a.severity === 'high').length ? 'danger' : undefined}
               onClick={() => setTab('anomalies')} />
          <Kpi label="Applied" value={s.recommendations.filter((r) => r.status === 'applied').length}
               tone="good" />
          <Kpi label="Dismissed"
               value={s.recommendations.filter((r) => r.status === 'dismissed').length} />
        </div>

        <Tabs active={tab} onChange={setTab} tabs={[
          { key: 'copilot', label: `Copilot (${pending.length})` },
          { key: 'assistant', label: 'Ask' },
          { key: 'anomalies', label: `Anomalies (${detected.length})` },
          { key: 'reports', label: 'Reports' },
          { key: 'history', label: `History (${handled.length})` },
        ]} />

        {tab === 'copilot' && (
          pending.length ? (
            <div className="rec-list" style={{ marginTop: 14 }}>
              {pending.map((r) => (
                <Card key={r.id}
                      title={<h3 className="row-flex">
                        <Pill tone={r.severity === 'critical' || r.severity === 'high' ? 'danger'
                          : r.severity === 'medium' ? 'warn' : 'info'}>
                          {titleCase(r.severity)}
                        </Pill>
                        {r.title}
                      </h3>}
                      actions={<span className="muted small">{relTime(r.createdAt, s.now)}</span>}
                      footer={
                        <div className="card-foot">
                          <span className="muted small">
                            {r.action
                              ? 'Applying runs the real action and writes to the audit log.'
                              : 'Advisory only — no automatic change is available for this one.'}
                          </span>
                          <div className="grow" />
                          <Button size="sm" onClick={() => setDismissing(r.id)}>
                            <IconClose size={13} /> Dismiss
                          </Button>
                          <Button size="sm" variant="primary"
                                  onClick={() => setConfirming({ recId: r.id })}>
                            <IconCheck size={13} /> Review &amp; apply
                          </Button>
                        </div>
                      }>
                  <p className="rec-situation">{r.situation}</p>
                  <div className="rec-grid">
                    <div>
                      <h4 className="micro-head">Evidence</h4>
                      <ul className="tight">
                        {r.evidence.map((e, i) => <li key={i}>{e}</li>)}
                      </ul>
                    </div>
                    <div>
                      <h4 className="micro-head">Recommendation</h4>
                      <p>{r.recommendation}</p>
                      <h4 className="micro-head">Expected impact</h4>
                      <p className="good">{r.expectedImpact}</p>
                    </div>
                  </div>
                  {r.entityType && r.entityId && (
                    <Button size="sm" onClick={() => app.open(r.entityType!, r.entityId!)}>
                      Open {r.entityType}
                    </Button>
                  )}
                </Card>
              ))}
            </div>
          ) : (
            <Empty title="Nothing to recommend right now"
                   body="The copilot checks late tasks, maintenance windows, repeat failures, electrification candidates, unassigned work and fuel anomalies. None of them currently warrant action."
                   action={<Button onClick={() => app.run(() => {
                     generateRecommendations(store); store.emit();
                   }, 'Scan complete')}>Re-scan</Button>} />
          )
        )}

        {tab === 'assistant' && (
          <div className="assistant" style={{ marginTop: 14 }}>
            <Card title="Ask about this fleet" pad={false}>
              <div className="chat-feed" ref={feedRef}>
                {!turns.length && (
                  <div className="chat-intro">
                    <IconSpark size={22} />
                    <h3>Ask in plain language</h3>
                    <p className="muted">
                      This answers from the organisation's live records — vehicles, trips, costs,
                      tasks, maintenance and documents. It has no knowledge beyond that, and it
                      will say so rather than guess.
                    </p>
                  </div>
                )}
                {turns.map((t) => (
                  <div key={t.id} className="chat-turn">
                    <div className="chat-q">{t.question}</div>
                    <div className="chat-a">
                      <p>{t.answer.answer}</p>

                      {t.answer.table && (
                        <div className="table-wrap" style={{ marginTop: 10 }}>
                          <table className="table compact">
                            <thead>
                              <tr>{t.answer.table.columns.map((c) => <th key={c}>{c}</th>)}</tr>
                            </thead>
                            <tbody>
                              {t.answer.table.rows.map((row, i) => (
                                <tr key={i}>
                                  {row.map((cell, j) => (
                                    <td key={j} className={typeof cell === 'number' ? 'num' : ''}>
                                      {cell}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}

                      {t.answer.proposal && !t.outcome && (
                        <div className="proposal">
                          <div className="proposal-head">
                            <IconSpark size={14} />
                            <strong>{t.answer.proposal.summary}</strong>
                            <Pill tone="warn">Not applied</Pill>
                          </div>
                          <ul className="tight">
                            {t.answer.proposal.affected.map((a, i) => (
                              <li key={i}><strong>{a.label}</strong> — {a.detail}</li>
                            ))}
                          </ul>
                          <div className="row-flex">
                            <Button size="sm" onClick={() => setTurns((prev) => prev.map(
                              (x) => x.id === t.id
                                ? { ...x, outcome: 'Declined — nothing was changed.' } : x))}>
                              Don't do it
                            </Button>
                            <Button size="sm" variant="primary"
                                    onClick={() => setConfirming({ turnId: t.id })}>
                              Review &amp; confirm
                            </Button>
                          </div>
                        </div>
                      )}

                      {t.outcome && (
                        <div className="banner good" style={{ marginTop: 10 }}>
                          <IconCheck size={14} /><div>{t.outcome}</div>
                        </div>
                      )}

                      {!!t.answer.followUps.length && (
                        <div className="chips" style={{ marginTop: 10 }}>
                          {t.answer.followUps.map((f) => (
                            <button key={f} className="chip" onClick={() => submit(f)}>{f}</button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              <div className="chat-input">
                <input className="input" value={question} placeholder="Ask about costs, maintenance, SLA, drivers…"
                       onChange={(e) => setQuestion(e.target.value)}
                       onKeyDown={(e) => { if (e.key === 'Enter') submit(question); }} />
                <Button variant="primary" onClick={() => submit(question)}
                        disabled={!question.trim()}>Ask</Button>
              </div>
            </Card>

            <Card title="Try one of these">
              <div className="chips column">
                {SUGGESTED_QUESTIONS.map((q) => (
                  <button key={q} className="chip" onClick={() => submit(q)}>{q}</button>
                ))}
              </div>
              <p className="muted small" style={{ marginTop: 12 }}>
                The last suggestion asks for a change rather than an answer. It will show you
                exactly which tasks it would cancel and wait for your confirmation.
              </p>
            </Card>
          </div>
        )}

        {tab === 'anomalies' && (
          detected.length ? (
            <Card title="Detected against each subject's own baseline" pad={false}
                  actions={<span className="muted small">
                    Not thresholds — deviations from that vehicle's or driver's own history
                  </span>}>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Severity</th><th>Kind</th><th>Subject</th><th>What changed</th>
                      <th>Baseline</th><th>Observed</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {detected.map((a, i) => (
                      <tr key={i}>
                        <td><Pill tone={a.severity === 'high' ? 'danger'
                          : a.severity === 'medium' ? 'warn' : 'info'}>
                          {titleCase(a.severity)}
                        </Pill></td>
                        <td>{titleCase(a.kind)}</td>
                        <td><strong>{a.subject}</strong></td>
                        <td className="muted">{a.detail}</td>
                        <td className="num">{a.baseline}</td>
                        <td className="num"><strong>{a.observed}</strong></td>
                        <td>
                          <Button size="sm" onClick={() => app.open(a.entityType, a.entityId)}>
                            Open
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          ) : (
            <Empty title="No anomalies"
                   body="Fuel consumption, idle time, driver event rates and route adherence are all within their own baselines." />
          )
        )}

        {tab === 'reports' && (
          <div className="grid-2" style={{ marginTop: 14 }}>
            <Card title="Weekly operations report"
                  actions={<Button size="sm" variant="primary" onClick={() => setReport(7)}>
                    <IconChart size={13} /> Generate
                  </Button>}>
              <p className="muted" style={{ marginTop: 0 }}>
                Compares the last 7 days against the 7 days before them: what happened, what
                improved, what deteriorated, the biggest risks and what to do about them.
              </p>
            </Card>
            <Card title="Monthly operations report"
                  actions={<Button size="sm" variant="primary" onClick={() => setReport(30)}>
                    <IconChart size={13} /> Generate
                  </Button>}>
              <p className="muted" style={{ marginTop: 0 }}>
                The same structure over 30 days, which smooths out single bad days and shows the
                real direction of travel.
              </p>
            </Card>
          </div>
        )}

        {tab === 'history' && (
          handled.length ? (
            <Card title="Handled recommendations" pad={false}>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>When</th><th>Recommendation</th><th>Outcome</th><th>Result</th><th>By</th>
                    </tr>
                  </thead>
                  <tbody>
                    {handled.map((r) => (
                      <tr key={r.id}>
                        <td>{relTime(r.appliedAt ?? r.dismissedAt ?? r.createdAt, s.now)}</td>
                        <td>
                          <strong>{r.title}</strong>
                          <div className="muted small">{r.recommendation}</div>
                        </td>
                        <td><Pill tone={r.status === 'applied' ? 'good' : 'neutral'}>
                          {titleCase(r.status)}
                        </Pill></td>
                        <td className="muted">{r.resultNote ?? '—'}</td>
                        <td>{r.appliedBy
                          ? s.users.find((u) => u.id === r.appliedBy)?.fullName ?? '—' : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          ) : (
            <Empty title="Nothing handled yet"
                   body="Applied and dismissed recommendations are kept here permanently, with who did it and what resulted." />
          )
        )}

        {confirmingRec && (
          <Confirm title="Apply this recommendation?"
                   body={confirmingRec.recommendation}
                   consequences={[
                     confirmingRec.expectedImpact,
                     confirmingRec.action
                       ? 'This runs the real action now and other modules will reflect it immediately.'
                       : 'No automatic change is available; this only records your acceptance.',
                     'The action is written to the audit log against your name.',
                   ]}
                   confirmLabel="Apply"
                   onCancel={() => setConfirming(null)}
                   onConfirm={() => {
                     app.run(() => {
                       const note = applyRecommendation(store, confirmingRec.id);
                       return note;
                     }, 'Recommendation applied');
                     setConfirming(null);
                   }} />
        )}

        {confirmingTurn?.answer.proposal && (
          <Confirm title={confirmingTurn.answer.proposal.summary}
                   body={`This affects ${confirmingTurn.answer.proposal.affected.length} record(s). Nothing has changed yet.`}
                   consequences={[
                     ...confirmingTurn.answer.proposal.affected
                       .slice(0, 6).map((a) => `${a.label} — ${a.detail}`),
                     ...(confirmingTurn.answer.proposal.affected.length > 6
                       ? [`…and ${confirmingTurn.answer.proposal.affected.length - 6} more`] : []),
                     'Cancelling a task notifies its customer contact and frees the vehicle.',
                   ]}
                   confirmLabel="Confirm and apply"
                   tone="danger"
                   onCancel={() => setConfirming(null)}
                   onConfirm={() => {
                     const turnId = confirmingTurn.id;
                     const note = app.run(
                       () => applyProposal(store, confirmingTurn.answer.proposal!),
                       'Applied');
                     if (note) {
                       setTurns((prev) => prev.map(
                         (x) => x.id === turnId ? { ...x, outcome: note } : x));
                     }
                     setConfirming(null);
                   }} />
        )}

        {dismissing && (
          <Confirm title="Dismiss this recommendation?"
                   body="It moves to history and the copilot will not raise the same one again while the situation is unchanged."
                   confirmLabel="Dismiss"
                   onCancel={() => setDismissing(null)}
                   onConfirm={() => {
                     app.run(() => dismissRecommendation(store, dismissing, 'Dismissed by operator'),
                             'Recommendation dismissed');
                     setDismissing(null);
                   }} />
        )}

        {report && <ReportModal days={report} onClose={() => setReport(null)} />}
      </div>
    </div>
  );
}

function ReportModal({ days, onClose }: { days: 7 | 30; onClose: () => void }) {
  const { store, state: s } = useApp();
  const r = useMemo(() => periodReport(store, days), [store, days]);
  return (
    <Modal title={`${r.period} — operations report`}
           subtitle={`Generated ${new Date(r.generatedAt).toLocaleString()} from ${s.org.name}'s own records`}
           size="lg" onClose={onClose}
           footer={<Button variant="primary" onClick={onClose}>Close</Button>}>
      <div className="report">
        <section>
          <h4 className="micro-head">What happened</h4>
          <ul className="tight">{r.happened.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </section>
        <section>
          <h4 className="micro-head good">What improved</h4>
          <ul className="tight">{r.improved.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </section>
        <section>
          <h4 className="micro-head bad">What deteriorated</h4>
          <ul className="tight">{r.deteriorated.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </section>
        <section>
          <h4 className="micro-head warn">Biggest risks</h4>
          <ul className="tight">{r.risks.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </section>
        <section>
          <h4 className="micro-head">Recommended actions</h4>
          <ol className="tight">{r.actions.map((x, i) => <li key={i}>{x}</li>)}</ol>
        </section>
      </div>
    </Modal>
  );
}
