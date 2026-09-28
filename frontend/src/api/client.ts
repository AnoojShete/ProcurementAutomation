import type { AccessTokenResponse, ApiEnvelope } from "@/types/api";

const API_BASE = "/api";

export class ApiError extends Error {
  code: string;
  status: number;
  /** The parsed JSON error body, when there was one. */
  body: unknown;
  constructor(message: string, code: string, status: number, body?: unknown) {
    super(message);
    this.code = code;
    this.status = status;
    this.body = body;
  }
}

// Access token lives in memory only. The refresh token is an httpOnly
// cookie set by auth-service: this code never sees it, so a script injected
// into the page can't steal it. The browser attaches it to /api/auth/*
// requests by itself; we prove the request came from our own page by
// echoing the readable csrf_token cookie in a header (see
// services/auth-service/app/session_cookies.py).
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

function csrfToken(): string | null {
  const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

/** Whether a signed-in session (cookie) exists — decides if a page reload
 * should try to restore it. */
export function hasSession(): boolean {
  return csrfToken() !== null;
}

async function refreshAccessToken(): Promise<string | null> {
  const csrf = csrfToken();
  if (!csrf) return null;
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-CSRF-Token": csrf },
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

/** Ends the session server-side (clears both cookies). */
export async function endSession(): Promise<void> {
  const csrf = csrfToken();
  accessToken = null;
  if (!csrf) return;
  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf },
    });
  } catch {
    /* offline: cookies expire on their own */
  }
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

async function parseErrorBody(res: Response): Promise<{ code: string; message: string; body?: unknown }> {
  let body: any;
  try {
    body = await res.json();
    if (body?.error?.message) return { code: body.error.code ?? "error", message: body.error.message, body };
    // A couple of raw FastAPI HTTPException paths (e.g. validation errors)
    // fall through to `{"detail": ...}` instead of the shared envelope.
    if (body?.detail)
      return { code: "error", message: typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail), body };
  } catch {
    /* no JSON body */
  }
  return { code: "http_error", message: res.statusText || `HTTP ${res.status}`, body };
}

/** rawFetch plus the shared 401 handling: one silent refresh-and-retry,
 * then sign-out. Returns the response for non-401 statuses as-is. */
async function authedFetch(path: string, opts: RequestOptions = {}): Promise<Response> {
  let res = await rawFetch(path, opts);

  if (res.status === 401 && !opts.skipAuthRetry) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      res = await rawFetch(path, opts);
    } else {
      accessToken = null;
      onUnauthorized?.();
      throw new ApiError("Session expired — please sign in again.", "unauthorized", 401);
    }
  }

  if (res.status === 401) {
    accessToken = null;
    onUnauthorized?.();
    throw new ApiError("Session expired — please sign in again.", "unauthorized", 401);
  }
  return res;
}

export async function apiRequest<T>(path: string, opts: RequestOptions = {}): Promise<ApiEnvelope<T>> {
  const res = await authedFetch(path, opts);
  if (!res.ok) {
    const { code, message, body } = await parseErrorBody(res);
    throw new ApiError(message, code, res.status, body);
  }

  if (res.status === 204) return { data: undefined as T };
  return (await res.json()) as ApiEnvelope<T>;
}

export const api = {
  get: <T,>(path: string, opts?: RequestOptions) => apiRequest<T>(path, { ...opts, method: "GET" }),
  post: <T,>(path: string, body?: unknown, opts?: RequestOptions) =>
    apiRequest<T>(path, { ...opts, method: "POST", body: body ?? {} }),
  patch: <T,>(path: string, body?: unknown, opts?: RequestOptions) =>
    apiRequest<T>(path, { ...opts, method: "PATCH", body: body ?? {} }),
  upload: <T,>(path: string, formData: FormData, opts?: RequestOptions) =>
    apiRequest<T>(path, { ...opts, method: "POST", body: formData }),
  request: <T,>(path: string, method: string, body?: unknown) => apiRequest<T>(path, { method, body }),
};

/** Fetches a file with the caller's token and hands it to the browser as a
 * download. A plain <a href> can't be used: the access token lives in
 * memory, not in a cookie. */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const res = await authedFetch(path, { method: "GET" });
  if (!res.ok) {
    const { code, message } = await parseErrorBody(res);
    throw new ApiError(message, code, res.status);
  }
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
