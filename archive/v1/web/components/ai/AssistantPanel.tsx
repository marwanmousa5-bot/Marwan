"use client";

/**
 * Fleet Assistant dock (Section 5, item 3).
 *
 * The hard rule from Section 9 is visible in the UI, not just the API: when
 * the assistant proposes a change it renders as a *pending* card with an
 * explicit Confirm button. Until that button is pressed nothing has been
 * sent to the confirm endpoint, so nothing in the fleet has changed. There
 * is no path in this component that applies an action automatically.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import type {
  AssistantActionResult,
  AssistantReply,
  PendingAction,
} from "@/lib/types";

interface Turn {
  id: number;
  role: "user" | "assistant";
  text: string;
  offline?: boolean;
  /** Set only on an action turn that is still waiting for confirmation. */
  pending?: PendingAction | null;
  affected?: string[];
  /** Set once the user has decided, so the card stops offering buttons. */
  outcome?: "applied" | "discarded";
}

let nextTurnId = 1;

export function AssistantPanel() {
  const { session } = useSession();
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  const canApply = session?.user.role === "org_admin";

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [turns, busy]);

  const ask = useCallback(
    async (text: string) => {
      setBusy(true);
      setError(null);
      setTurns((current) => [
        ...current,
        { id: nextTurnId++, role: "user", text },
      ]);
      try {
        const reply = await api.post<AssistantReply>("/assistant/ask", {
          question: text,
        });
        const affected = Array.isArray(reply.data?.tasks)
          ? (reply.data.tasks as string[])
          : [];
        setTurns((current) => [
          ...current,
          {
            id: nextTurnId++,
            role: "assistant",
            text: reply.answer,
            offline: reply.offline,
            pending: reply.pending_action,
            affected,
          },
        ]);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : strings.assistant.failed);
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text || busy) return;
    setQuestion("");
    await ask(text);
  }

  /** The only mutating call in this component, and it needs a click. */
  async function confirm(turn: Turn) {
    if (!turn.pending) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<AssistantActionResult>("/assistant/confirm", {
        pending_action: turn.pending,
      });
      setTurns((current) => [
        ...current.map((t) =>
          t.id === turn.id ? { ...t, pending: null, outcome: "applied" as const } : t,
        ),
        { id: nextTurnId++, role: "assistant", text: result.message },
      ]);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : strings.assistant.confirmFailed,
      );
    } finally {
      setBusy(false);
    }
  }

  function discard(turn: Turn) {
    setTurns((current) =>
      current.map((t) =>
        t.id === turn.id ? { ...t, pending: null, outcome: "discarded" as const } : t,
      ),
    );
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full bg-electric px-4 py-2.5 text-sm font-medium text-white shadow-xl transition hover:bg-electric-600"
      >
        <PulseGlyph />
        {strings.assistant.open}
      </button>
    );
  }

  return (
    <section
      aria-label={strings.assistant.title}
      className="fixed bottom-5 right-5 z-40 flex h-[32rem] w-[min(24rem,calc(100vw-2.5rem))] flex-col rounded-xl border border-ink-600 bg-ink-800 shadow-2xl"
    >
      <header className="flex items-center justify-between border-b border-ink-700 px-4 py-3">
        <span className="flex items-center gap-2 text-sm font-semibold text-white">
          <PulseGlyph />
          {strings.assistant.title}
        </span>
        <button
          onClick={() => setOpen(false)}
          aria-label={strings.assistant.close}
          className="rounded p-1 text-ink-400 hover:bg-ink-700 hover:text-white"
        >
          ×
        </button>
      </header>

      <div ref={logRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {turns.length === 0 && (
          <p className="text-xs leading-relaxed text-ink-400">
            {strings.assistant.intro}
          </p>
        )}

        {turns.map((turn) =>
          turn.role === "user" ? (
            <p
              key={turn.id}
              className="ml-6 rounded-lg rounded-br-sm bg-electric/15 px-3 py-2 text-xs text-electric-100"
            >
              {turn.text}
            </p>
          ) : (
            <div key={turn.id} className="mr-6 space-y-2">
              <p className="rounded-lg rounded-bl-sm bg-ink-700/70 px-3 py-2 text-xs leading-relaxed text-ink-100">
                {turn.text}
              </p>

              {turn.offline && (
                <p className="px-1 text-[10px] leading-relaxed text-ink-500">
                  {strings.assistant.offlineNote}
                </p>
              )}

              {turn.pending && (
                <div className="rounded-lg border border-warning/40 bg-warning/5 p-3">
                  <p className="text-[11px] font-semibold text-warning">
                    {strings.assistant.confirmTitle}
                  </p>
                  <p className="mt-1 text-[11px] leading-relaxed text-ink-300">
                    {strings.assistant.confirmHint}
                  </p>

                  {turn.affected && turn.affected.length > 0 && (
                    <div className="mt-2">
                      <p className="fb-label">
                        {strings.assistant.affected} ({turn.pending.affected_count})
                      </p>
                      <ul className="mt-1 space-y-0.5">
                        {turn.affected.map((name) => (
                          <li key={name} className="truncate text-[11px] text-ink-200">
                            · {name}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <p className="mt-2 text-[10px] text-ink-500">
                    {strings.assistant.expires}{" "}
                    {new Date(turn.pending.expires_at).toLocaleTimeString()}
                  </p>

                  {canApply ? (
                    <div className="mt-3 flex gap-2">
                      <button
                        onClick={() => confirm(turn)}
                        disabled={busy}
                        className="fb-button-primary !py-1.5 text-xs disabled:opacity-50"
                      >
                        {strings.assistant.confirm}
                      </button>
                      <button
                        onClick={() => discard(turn)}
                        className="fb-button-ghost !py-1.5 text-xs"
                      >
                        {strings.assistant.discard}
                      </button>
                    </div>
                  ) : (
                    <p className="mt-3 text-[11px] text-ink-400">
                      {strings.assistant.adminOnly}
                    </p>
                  )}
                </div>
              )}

              {turn.outcome === "applied" && (
                <p className="px-1 text-[11px] text-success">
                  {strings.assistant.applied}
                </p>
              )}
              {turn.outcome === "discarded" && (
                <p className="px-1 text-[11px] text-ink-500">
                  {strings.assistant.discard}
                </p>
              )}
            </div>
          ),
        )}

        {busy && <p className="text-[11px] text-ink-400">{strings.assistant.thinking}</p>}
        {error && (
          <p role="alert" className="text-[11px] text-danger">
            {error}
          </p>
        )}
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2 border-t border-ink-700 p-3">
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={strings.assistant.placeholder}
          aria-label={strings.assistant.placeholder}
          className="fb-input !py-1.5 text-xs"
        />
        <button
          type="submit"
          disabled={busy || question.trim().length === 0}
          className="fb-button-primary !py-1.5 text-xs disabled:opacity-40"
        >
          {strings.assistant.send}
        </button>
      </form>
    </section>
  );
}

function PulseGlyph() {
  return (
    <svg width="16" height="10" viewBox="0 0 16 10" aria-hidden="true" fill="none">
      <path
        d="M0 5h3.5l1.5-4 2 8 2-6 1.5 2H16"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
