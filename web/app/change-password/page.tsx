"use client";

/**
 * Password change, and the gate for a forced one (Section 4a).
 *
 * A seeded or reset account carries `must_change_password`, and the API
 * refuses every other endpoint until it is cleared - so this page has to work
 * for someone who is signed in but can do nothing else. It reads the flag
 * from the session and changes its own wording rather than pretending the
 * visit was voluntary.
 */

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { ApiError, api, tokenStore } from "@/lib/api";
import { homePathForRole, useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import { Logo } from "@/components/Logo";
import { PulseLoader } from "@/components/PulseLoader";

const MIN_LENGTH = 12;

export default function ChangePasswordPage() {
  const { session, loading, signOut } = useSession();
  const router = useRouter();

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  const forced = session?.user.must_change_password ?? false;

  useEffect(() => {
    if (!loading && !session) router.replace("/login");
  }, [loading, session, router]);

  if (loading || !session) return <PulseLoader />;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (next !== confirm) {
      setError(strings.changePassword.mismatch);
      return;
    }
    if (next.length < MIN_LENGTH) {
      setError(strings.changePassword.tooShort);
      return;
    }
    if (next === current) {
      setError(strings.changePassword.sameAsCurrent);
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await api.post("/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      // The API revokes every refresh token on a password change, so the
      // tokens in hand are dead. Clear them rather than letting the next
      // call fail in a confusing way.
      tokenStore.clear();
      setDone(true);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : strings.changePassword.failed,
      );
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
            <p className="text-sm text-success">{strings.changePassword.success}</p>
            <button
              onClick={() => router.replace("/login")}
              className="fb-button-primary w-full"
            >
              {strings.login.submit}
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="fb-card space-y-5 p-7">
            <div>
              <h1 className="text-lg font-semibold text-white">
                {forced
                  ? strings.changePassword.forcedTitle
                  : strings.changePassword.title}
              </h1>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-300">
                {forced
                  ? strings.changePassword.forcedSubtitle
                  : strings.changePassword.subtitle}
              </p>
            </div>

            <label className="block">
              <span className="fb-label">{strings.changePassword.current}</span>
              <input
                type="password"
                required
                autoComplete="current-password"
                value={current}
                onChange={(event) => setCurrent(event.target.value)}
                className="fb-input mt-1"
              />
            </label>

            <label className="block">
              <span className="fb-label">{strings.changePassword.new}</span>
              <input
                type="password"
                required
                minLength={MIN_LENGTH}
                autoComplete="new-password"
                value={next}
                onChange={(event) => setNext(event.target.value)}
                className="fb-input mt-1"
              />
            </label>

            <label className="block">
              <span className="fb-label">{strings.changePassword.confirm}</span>
              <input
                type="password"
                required
                autoComplete="new-password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                className="fb-input mt-1"
              />
            </label>

            {error && (
              <p role="alert" className="text-xs text-danger">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="fb-button-primary w-full disabled:opacity-50"
            >
              {submitting
                ? strings.changePassword.submitting
                : strings.changePassword.submit}
            </button>

            {!forced && (
              <button
                type="button"
                onClick={() => router.replace(homePathForRole(session.user.role))}
                className="w-full text-center text-xs text-ink-400 hover:text-ink-200"
              >
                {strings.common.cancel}
              </button>
            )}

            {forced && (
              <button
                type="button"
                onClick={async () => {
                  await signOut();
                  router.replace("/login");
                }}
                className="w-full text-center text-xs text-ink-400 hover:text-ink-200"
              >
                {strings.nav.signOut}
              </button>
            )}
          </form>
        )}
      </div>
    </main>
  );
}
