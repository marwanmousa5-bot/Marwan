"use client";

/**
 * Client-side session context.
 *
 * Role routing rule (Sections 4a and 4b):
 *   super_admin            -> /platform-admin  (never the customer console)
 *   org_admin, dispatcher  -> /dashboard       (Live Tracking is the landing page)
 *   driver                 -> mobile app only; rejected here with an explanation
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";

import { api, tokenStore } from "./api";
import type { CurrentUser, Session, UserRole } from "./types";

interface SessionContextValue {
  session: CurrentUser | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<CurrentUser>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function homePathForRole(role: UserRole): string {
  if (role === "super_admin") return "/platform-admin";
  if (role === "driver") return "/login?driver=1";
  return "/dashboard";
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!tokenStore.read()) {
      setSession(null);
      setLoading(false);
      return;
    }
    try {
      setSession(await api.get<CurrentUser>("/auth/me"));
    } catch {
      tokenStore.clear();
      setSession(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const signIn = useCallback(async (email: string, password: string) => {
    const result = await api.post<Session>(
      "/auth/login",
      { email, password },
      true,
    );
    tokenStore.write(result.tokens);
    const current: CurrentUser = {
      user: result.user,
      organization_name: result.organization_name,
      organization_timezone: result.organization_timezone,
      is_impersonating: result.is_impersonating,
    };
    setSession(current);
    return current;
  }, []);

  const signOut = useCallback(async () => {
    const tokens = tokenStore.read();
    if (tokens) {
      try {
        await api.post("/auth/logout", { refresh_token: tokens.refresh_token });
      } catch {
        /* signing out locally matters more than the server round-trip */
      }
    }
    tokenStore.clear();
    setSession(null);
  }, []);

  const value = useMemo(
    () => ({ session, loading, signIn, signOut, refresh: load }),
    [session, loading, signIn, signOut, load],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSession must be used inside a SessionProvider");
  }
  return context;
}

/**
 * Client-side guard. The real enforcement is server-side RBAC on every API
 * call - this only keeps users out of screens they have no data for.
 */
export function useRequireRole(allowed: UserRole[]) {
  const { session, loading } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!session) {
      router.replace("/login");
      return;
    }
    // A forced password change outranks the role check: the API refuses every
    // console endpoint until it is cleared, so landing anywhere else would
    // just render a screen full of 403s (Section 4a).
    if (session.user.must_change_password) {
      router.replace("/change-password");
      return;
    }
    if (!allowed.includes(session.user.role)) {
      router.replace(homePathForRole(session.user.role));
    }
    // `allowed` is a literal array at every call site.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, loading, router]);

  return { session, loading };
}
