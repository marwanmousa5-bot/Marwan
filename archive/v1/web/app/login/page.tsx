"use client";

import { Suspense, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { ApiError } from "@/lib/api";
import { homePathForRole, useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import { Logo } from "@/components/Logo";

function LoginForm() {
  const { signIn } = useSession();
  const router = useRouter();
  const params = useSearchParams();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(
    params.get("driver")
      ? "Driver accounts use the FleetBeat mobile app, not this console."
      : null,
  );
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const session = await signIn(email, password);
      router.replace(
        session.user.must_change_password
          ? "/change-password"
          : homePathForRole(session.user.role),
      );
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : strings.login.genericError,
      );
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-ink-900 px-4 py-12">
      {/* A restrained pulse behind the card - brand presence without noise. */}
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 bg-[radial-gradient(60rem_40rem_at_50%_-10%,rgba(30,144,255,0.12),transparent)]"
      />

      <div className="relative w-full max-w-md">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <Logo />
          <p className="text-sm text-ink-300">{strings.brand.tagline}</p>
        </div>

        <form onSubmit={handleSubmit} className="fb-card space-y-5 p-7">
          <div>
            <h1 className="text-lg font-semibold text-white">
              {strings.login.title}
            </h1>
            <p className="mt-1 text-sm text-ink-300">
              {strings.login.subtitle}
            </p>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="email" className="fb-label">
              {strings.login.emailLabel}
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="fb-input"
              placeholder="you@company.com"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="password" className="fb-label">
              {strings.login.passwordLabel}
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="fb-input"
              placeholder="••••••••••••"
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
            {submitting ? strings.login.submitting : strings.login.submit}
          </button>

          {/*
            There is no sign-up link because there is no sign-up (Section 9).
            Saying so plainly is better UX than leaving people hunting for it.
          */}
          <p className="border-t border-ink-600/60 pt-4 text-xs leading-relaxed text-ink-400">
            {strings.login.noSignup}
          </p>
        </form>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
