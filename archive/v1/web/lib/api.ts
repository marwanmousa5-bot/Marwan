/**
 * Typed client for the FleetBeat API.
 *
 * Token handling decision for MVP: the access/refresh pair is kept in
 * `localStorage` and attached as a bearer header, because the API is a
 * separate origin from the web app and the Flutter driver app consumes the
 * exact same endpoints. The hardening path (httpOnly refresh cookie +
 * same-site proxy route) is noted in PROGRESS.md and does not change any
 * API contract.
 */
import type { TokenPair } from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

const ACCESS_KEY = "fleetbeat.access_token";
const REFRESH_KEY = "fleetbeat.refresh_token";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export const tokenStore = {
  read(): TokenPair | null {
    if (typeof window === "undefined") return null;
    const access = window.localStorage.getItem(ACCESS_KEY);
    const refresh = window.localStorage.getItem(REFRESH_KEY);
    if (!access || !refresh) return null;
    return {
      access_token: access,
      refresh_token: refresh,
      token_type: "bearer",
      expires_in: 0,
    };
  },
  write(tokens: TokenPair) {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(ACCESS_KEY, tokens.access_token);
    window.localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  },
  clear() {
    if (typeof window === "undefined") return;
    window.localStorage.removeItem(ACCESS_KEY);
    window.localStorage.removeItem(REFRESH_KEY);
  },
};

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  /** Skip the bearer header (login, activation). */
  anonymous?: boolean;
  /** Internal: prevents an infinite refresh loop. */
  retried?: boolean;
}

async function parseError(response: Response): Promise<ApiError> {
  let code = "error";
  let detail = response.statusText || "Request failed";
  try {
    const body = await response.json();
    if (typeof body?.code === "string") code = body.code;
    if (typeof body?.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body?.detail) && body.detail.length > 0) {
      // FastAPI validation errors.
      detail = body.detail
        .map((d: { msg?: string }) => d?.msg)
        .filter(Boolean)
        .join(", ");
      code = "validation_error";
    }
  } catch {
    /* non-JSON error body - keep the status text */
  }
  return new ApiError(response.status, code, detail);
}

async function refreshTokens(): Promise<boolean> {
  const tokens = tokenStore.read();
  if (!tokens) return false;

  const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: tokens.refresh_token }),
  });
  if (!response.ok) {
    tokenStore.clear();
    return false;
  }
  tokenStore.write((await response.json()) as TokenPair);
  return true;
}

export async function apiFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, anonymous = false, retried = false } = options;

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (!anonymous) {
    const tokens = tokenStore.read();
    if (tokens) headers.Authorization = `Bearer ${tokens.access_token}`;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });

  // One transparent refresh attempt on an expired access token.
  if (response.status === 401 && !anonymous && !retried) {
    if (await refreshTokens()) {
      return apiFetch<T>(path, { ...options, retried: true });
    }
  }

  if (!response.ok) {
    const failure = await parseError(response);
    // A tab left open across a password reset would otherwise sit there
    // rendering 403s. Send it where the only useful action is (Section 4a).
    if (
      failure.code === "password_change_required" &&
      typeof window !== "undefined" &&
      window.location.pathname !== "/change-password"
    ) {
      window.location.assign("/change-password");
    }
    throw failure;
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown, anonymous = false) =>
    apiFetch<T>(path, { method: "POST", body, anonymous }),
  patch: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: "PATCH", body }),
  delete: <T>(path: string) => apiFetch<T>(path, { method: "DELETE" }),
};

/**
 * Download an authenticated file (CSV/PDF exports).
 *
 * Exports are bearer-authenticated like every other endpoint, so a plain
 * `<a href>` would come back 401. We fetch the bytes, hand the browser an
 * object URL, and revoke it straight after the click.
 */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const tokens = tokenStore.read();
  const headers: Record<string, string> = {};
  if (tokens) headers.Authorization = `Bearer ${tokens.access_token}`;

  let response = await fetch(`${API_BASE_URL}${path}`, { headers, cache: "no-store" });
  if (response.status === 401 && (await refreshTokens())) {
    const retryTokens = tokenStore.read();
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: retryTokens
        ? { Authorization: `Bearer ${retryTokens.access_token}` }
        : {},
      cache: "no-store",
    });
  }
  if (!response.ok) throw await parseError(response);

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/**
 * WebSocket URL for the live feed.
 *
 * The access token travels as a query parameter because browsers cannot set
 * headers on a WebSocket handshake. It is the same short-lived signed token
 * the REST API uses, and the server still derives the Organization from the
 * token rather than trusting anything the client sends.
 */
export function liveSocketUrl(): string | null {
  const tokens = tokenStore.read();
  if (!tokens) return null;
  const base = API_BASE_URL.replace(/^http/, "ws");
  return `${base}/live/ws?token=${encodeURIComponent(tokens.access_token)}`;
}
