"use client";

/**
 * Reports, maintenance windows and exports (Sections 5 item 5, 4 item 13).
 *
 * Three blocks, in the order a fleet manager works through them: the
 * narrative summary (what happened), the proposed maintenance windows (what
 * to decide), and the exports (what to send on). Maintenance windows are
 * proposals - the page says so on every card that was not auto-booked.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError, api, downloadFile } from "@/lib/api";
import { strings } from "@/lib/strings";
import type { MaintenanceProposal, ReportSummary } from "@/lib/types";

const PERIODS = [
  { value: "weekly", label: strings.reports.weekly },
  { value: "monthly", label: strings.reports.monthly },
] as const;

const EXPORT_RANGES = [
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
  { days: 365, label: "12 months" },
] as const;

function isoDaysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

function periodLabel(summary: ReportSummary): string {
  const start = new Date(summary.period_start).toLocaleDateString();
  const end = new Date(summary.period_end).toLocaleDateString();
  return `${start} – ${end}`;
}

export default function ReportsPage() {
  const [summaries, setSummaries] = useState<ReportSummary[]>([]);
  const [period, setPeriod] = useState<"weekly" | "monthly">("weekly");
  const [generating, setGenerating] = useState(false);
  const [proposals, setProposals] = useState<MaintenanceProposal[] | null>(null);
  const [proposing, setProposing] = useState(false);
  const [exportDays, setExportDays] = useState<number>(30);
  const [exporting, setExporting] = useState<"csv" | "pdf" | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setSummaries(await api.get<ReportSummary[]>("/reports/summaries"));
      setError(null);
    } catch {
      setError("We could not load your reports.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function generate() {
    setGenerating(true);
    setError(null);
    try {
      const summary = await api.post<ReportSummary>(
        `/reports/summaries?period_type=${period}`,
      );
      setSummaries((current) => [summary, ...current]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We could not generate that.");
    } finally {
      setGenerating(false);
    }
  }

  async function proposeWindows() {
    setProposing(true);
    setError(null);
    try {
      setProposals(
        await api.post<MaintenanceProposal[]>("/copilot/maintenance-windows"),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We could not propose windows.");
    } finally {
      setProposing(false);
    }
  }

  async function exportCosts(fmt: "csv" | "pdf") {
    setExporting(fmt);
    setError(null);
    try {
      await downloadFile(
        `/reports/costs.${fmt}?date_from=${isoDaysAgo(exportDays)}`,
        `fleetbeat-costs-${isoDaysAgo(exportDays)}.${fmt}`,
      );
    } catch {
      setError(strings.reports.exportFailed);
    } finally {
      setExporting(null);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-white">{strings.reports.title}</h1>
        <p className="mt-1 text-sm text-ink-300">{strings.reports.subtitle}</p>
      </div>

      {error && (
        <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </p>
      )}

      {/* --- narrative summaries --- */}
      <section className="fb-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-white">
            {strings.reports.summariesTitle}
          </h2>
          <div className="flex items-center gap-2">
            <div className="flex rounded-md border border-ink-600">
              {PERIODS.map((option) => (
                <button
                  key={option.value}
                  onClick={() => setPeriod(option.value)}
                  aria-pressed={period === option.value}
                  className={`px-3 py-1.5 text-xs transition ${
                    period === option.value
                      ? "bg-electric text-white"
                      : "text-ink-300 hover:bg-ink-700"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <button
              onClick={generate}
              disabled={generating}
              className="fb-button-primary !py-1.5 text-xs disabled:opacity-50"
            >
              {generating ? strings.reports.generating : strings.reports.generate}
            </button>
          </div>
        </div>

        <div className="mt-4 space-y-3">
          {loading ? (
            <p className="text-xs text-ink-400">{strings.common.loading}</p>
          ) : summaries.length === 0 ? (
            <p className="text-xs text-ink-400">{strings.reports.summariesEmpty}</p>
          ) : (
            summaries.map((summary) => (
              <article
                key={summary.id}
                className="rounded-lg border border-ink-700 bg-ink-800/60 p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="fb-badge bg-electric/15 text-electric-300">
                    {summary.period_type}
                  </span>
                  <span className="fb-numeric text-[11px] text-ink-400">
                    {periodLabel(summary)}
                  </span>
                </div>
                <p className="mt-2 whitespace-pre-line text-xs leading-relaxed text-ink-100">
                  {summary.summary_text}
                </p>
                <p className="mt-2 text-[10px] text-ink-500">
                  {strings.reports.generatedBy} {summary.generated_by} ·{" "}
                  {new Date(summary.created_at).toLocaleString()}
                </p>
              </article>
            ))
          )}
        </div>
      </section>

      {/* --- maintenance windows --- */}
      <section className="fb-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-white">
            {strings.reports.windowsTitle}
          </h2>
          <button
            onClick={proposeWindows}
            disabled={proposing}
            className="fb-button-ghost !py-1.5 text-xs disabled:opacity-50"
          >
            {proposing ? strings.copilot.running : strings.reports.windowsRun}
          </button>
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-ink-400">
          {strings.reports.windowsHint}
        </p>

        <div className="mt-4 space-y-2">
          {proposals === null ? (
            <p className="text-xs text-ink-400">{strings.common.empty}</p>
          ) : proposals.length === 0 ? (
            <p className="text-xs text-ink-400">{strings.reports.windowsEmpty}</p>
          ) : (
            proposals.map((proposal) => (
              <article
                key={`${proposal.vehicle_id}-${proposal.schedule_id}`}
                className="rounded-lg border border-ink-700 bg-ink-800/60 p-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs font-medium text-ink-50">
                    {proposal.vehicle_name} · {proposal.schedule_name}
                  </p>
                  <span
                    className={`fb-badge ${
                      proposal.auto_booked
                        ? "bg-success/15 text-success"
                        : "bg-ink-700 text-ink-300"
                    }`}
                  >
                    {proposal.auto_booked
                      ? strings.reports.autoBooked
                      : strings.reports.proposalOnly}
                  </span>
                </div>
                <p className="fb-numeric mt-1 text-xs text-electric-300">
                  {new Date(proposal.proposed_date).toLocaleDateString(undefined, {
                    weekday: "short",
                    day: "numeric",
                    month: "short",
                  })}
                  <span className="ml-2 text-ink-500">
                    {proposal.tasks_that_day} {strings.reports.tasksThatDay}
                  </span>
                </p>
                <p className="mt-1 text-[11px] leading-relaxed text-ink-400">
                  {proposal.rationale}
                </p>
              </article>
            ))
          )}
        </div>
      </section>

      {/* --- exports --- */}
      <section className="fb-card">
        <h2 className="text-sm font-semibold text-white">
          {strings.reports.exportsTitle}
        </h2>
        <p className="mt-1 text-[11px] text-ink-400">{strings.reports.exportsHint}</p>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="flex rounded-md border border-ink-600">
            {EXPORT_RANGES.map((range) => (
              <button
                key={range.days}
                onClick={() => setExportDays(range.days)}
                aria-pressed={exportDays === range.days}
                className={`px-3 py-1.5 text-xs transition ${
                  exportDays === range.days
                    ? "bg-electric text-white"
                    : "text-ink-300 hover:bg-ink-700"
                }`}
              >
                {range.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => exportCosts("csv")}
            disabled={exporting !== null}
            className="fb-button-ghost !py-1.5 text-xs disabled:opacity-50"
          >
            {exporting === "csv" ? strings.common.loading : strings.reports.exportCsv}
          </button>
          <button
            onClick={() => exportCosts("pdf")}
            disabled={exporting !== null}
            className="fb-button-ghost !py-1.5 text-xs disabled:opacity-50"
          >
            {exporting === "pdf" ? strings.common.loading : strings.reports.exportPdf}
          </button>
        </div>
      </section>
    </div>
  );
}
