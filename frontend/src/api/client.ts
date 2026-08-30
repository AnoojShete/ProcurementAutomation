import type { AccessTokenResponse, ApiEnvelope } from "@/types/api";

const API_BASE = "/api";
const REFRESH_TOKEN_KEY = "itpip.refresh_token";

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(message: string, code: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

// Access token lives in memory only (never localStorage) — the refresh
// token is the only thing persisted, matching a short-lived-access-token /
// longer-lived-refresh-token design without exposing the access token to
// anything that can read localStorage.
let accessToken: string | null = null;
let onUnauthorized: (() => void) | null = null;
let refreshInFlight: Promise<string | null> | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}
export function getAccessToken() {
  return accessToken;
}
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}
export function getStoredRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}
export function setStoredRefreshToken(token: string | null) {
  if (token) localStorage.setItem(REFRESH_TOKEN_KEY, token);
  else localStorage.removeItem(REFRESH_TOKEN_KEY);
}

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getStoredRefreshToken();
  if (!refreshToken) return null;
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!res.ok) return null;
        const body = (await res.json()) as ApiEnvelope<AccessTokenResponse>;
        accessToken = body.data.access_token;
        return accessToken;
      } catch {
        return null;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  skipAuthRetry?: boolean;
}

async function rawFetch(path: string, opts: RequestOptions = {}): Promise<Response> {
  const headers = new Headers(opts.headers);
  const isFormData = opts.body instanceof FormData;
  if (!isFormData) headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  return fetch(`${API_BASE}${path}`, {
    ...opts,
    headers,
    body: isFormData ? (opts.body as FormData) : opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
}

async function parseErrorBody(res: Response): Promise<{ code: string; message: string }> {
  try {
    const body = await res.json();
    if (body?.error?.message) return { code: body.error.code ?? "error", message: body.error.message };
    // A couple of raw FastAPI HTTPException paths (e.g. validation errors)
    // fall through to `{"detail": ...}` instead of the shared envelope.
    if (body?.detail) return { code: "error", message: typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail) };
  } catch {
    /* no JSON body */
  }
  return { code: "http_error", message: res.statusText || `HTTP ${res.status}` };
}

export async function apiRequest<T>(path: string, opts: RequestOptions = {}): Promise<ApiEnvelope<T>> {
  let res = await rawFetch(path, opts);

  if (res.status === 401 && !opts.skipAuthRetry) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      res = await rawFetch(path, opts);
    } else {
      setStoredRefreshToken(null);
      accessToken = null;
      onUnauthorized?.();
      throw new ApiError("Session expired — please sign in again.", "unauthorized", 401);
    }
  }

  if (res.status === 401) {
    setStoredRefreshToken(null);
    accessToken = null;
    onUnauthorized?.();
    throw new ApiError("Session expired — please sign in again.", "unauthorized", 401);
  }

  if (!res.ok) {
    const { code, message } = await parseErrorBody(res);
    throw new ApiError(message, code, res.status);
  }

  if (res.status === 204) return { data: undefined as T };
  return (await res.json()) as ApiEnvelope<T>;
}

export const api = {
  get: <T,>(path: string, opts?: RequestOptions) => apiRequest<T>(path, { ...opts, method: "GET" }),
  post: <T,>(path: string, body?: unknown, opts?: RequestOptions) =>
    apiRequest<T>(path, { ...opts, method: "POST", body: body ?? {} }),
  upload: <T,>(path: string, formData: FormData, opts?: RequestOptions) =>
    apiRequest<T>(path, { ...opts, method: "POST", body: formData }),
};
