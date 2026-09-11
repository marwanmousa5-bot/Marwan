"use client";

import { Suspense, useState, type FormEvent } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import { strings } from "@/lib/strings";
import { Logo } from "@/components/Logo";

/**
 * Consumes the one-time activation link a FleetBeat staff member (or an Org
 * Admin) handed over. This is the only path by which a new account gets a
 * password - there is no self-service registration.
 */
function ActivateForm() {
  const token = useSearchParams().get("token");

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setError(strings.activate.mismatch);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/auth/activate", { token, password }, true);
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-ink-900 px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 flex justify-center">
          <Logo />
        </div>

        {done ? (
          <div className="fb-card space-y-4 p-7 text-center">
            <p className="text-sm text-success">{strings.activate.success}</p>
            <Link href="/login" className="fb-button-primary w-full">
              {strings.login.submit}
            </Link>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="fb-card space-y-5 p-7">
            <div>
              <h1 className="text-lg font-semibold text-white">
                {strings.activate.title}
              </h1>
              <p className="mt-1 text-sm text-ink-300">
                {strings.activate.subtitle}
              </p>
            </div>

            {!token ? (
              <p
                role="alert"
                className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning"
              >
                {strings.activate.missingToken}
              </p>
            ) : (
              <>
                <div className="space-y-1.5">
                  <label htmlFor="password" className="fb-label">
                    {strings.activate.passwordLabel}
                  </label>
                  <input
                    id="password"
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={12}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="fb-input"
                  />
                  <p className="text-xs text-ink-400">
                    {strings.activate.requirements}
                  </p>
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="confirm" className="fb-label">
                    {strings.activate.confirmLabel}
                  </label>
                  <input
                    id="confirm"
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={12}
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    className="fb-input"
                  />
                </div>

                {error && (
                  <p
                    role="alert"
                    className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
                  >
                    {error}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={submitting}
                  className="fb-button-primary w-full"
                >
                  {submitting
                    ? strings.activate.submitting
                    : strings.activate.submit}
                </button>
              </>
            )}
          </form>
        )}
      </div>
    </main>
  );
}

export default function ActivatePage() {
  return (
    <Suspense>
      <ActivateForm />
    </Suspense>
  );
}
