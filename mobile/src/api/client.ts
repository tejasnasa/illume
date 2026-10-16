/**
 * The single ``fetch`` wrapper the app uses to reach the backend.
 *
 * Every API call routes through :func:`apiRequest`; everything that touches the
 * network lives here. The client is intentionally tiny:
 *
 * - Reads the base URL from ``EXPO_PUBLIC_BACKEND_URL`` at call time. That
 *   variable is statically inlined at bundle time by Expo, so a release
 *   build cannot accidentally regress to ``localhost`` when the env var is
 *   missing in CI -- the local fallback is the Android emulator's special
 *   host alias ``10.0.2.2`` rather than the desktop loopback, which would
 *   resolve to the emulator itself.
 * - Reads the bearer token from :mod:`src.lib.tokenStore` on every request.
 *   Secure store reads are in-memory after the first hit, so the cost is
 *   negligible, and reading lazily means query functions, callbacks, and
 *   one-off callers all behave the same way without a React context bridge.
 * - Throws an :class:`ApiError` on any non-2xx response or network failure
 *   so React Query (and direct callers) can branch on ``kind``.
 *
 * Tests inject a ``fetchImpl`` and an explicit ``backendUrl``; production
 * code never has to think about either.
 */

import {
  ApiError,
  kindFromStatus,
  type ApiErrorKind,
} from "@/lib/apiError";
import { getAccessToken } from "@/lib/tokenStore";

/**
 * Default backend URL when the env var is unset.
 *
 * ``10.0.2.2`` is the Android emulator's loopback alias for the host
 * machine; on iOS simulator ``localhost`` works, and a real device needs a
 * LAN IP set in ``.env``. The fallback exists so a fresh checkout does not
 * crash with ``Cannot read property of undefined`` -- a missing env var
 * produces a connection error against the emulator instead, which is the
 * cheaper failure to debug.
 */
export const DEFAULT_BACKEND_URL = "http://10.0.2.2:8000";

/**
 * Return the configured backend base URL.
 *
 * The env var is read lazily so a process that imports this module without
 * the variable present (tests, scripts) does not blow up at import time.
 */
export function resolveBackendUrl(override?: string): string {
  if (override) return override.replace(/\/+$/, "");
  const envValue = (process.env as Record<string, string | undefined>)
    .EXPO_PUBLIC_BACKEND_URL;
  return (envValue ?? DEFAULT_BACKEND_URL).replace(/\/+$/, "");
}

export interface ApiRequestOptions {
  /** HTTP method. ``GET`` when omitted. */
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** JSON body to serialise. Skipped when undefined. */
  body?: unknown;
  /** Extra request headers. ``Authorization`` and ``Content-Type`` are set automatically. */
  headers?: Record<string, string>;
  /** Signal forwarded from a caller-owned ``AbortController``. */
  signal?: AbortSignal;
  /** Override the default backend URL. Used by tests; production callers leave it unset. */
  backendUrl?: string;
  /**
   * Override the default token source. Production callers leave it unset
   * and the secure store is consulted; tests inject a constant.
   */
  getToken?: () => Promise<string | null>;
  /** Override the global ``fetch``. Tests inject a mock. */
  fetchImpl?: typeof fetch;
}

export interface ApiRequestResult<T> {
  status: number;
  body: T;
}

const JSON_CONTENT_TYPE = "application/json";

/**
 * Issue an authenticated request against the backend.
 *
 * The path is appended to the backend base URL with a leading slash so the
 * caller can pass either ``"/auth/me"`` or ``"auth/me"`` interchangeably.
 * A 204 response returns ``undefined`` as the body so callers can ignore
 * the parsing step on deletes.
 */
export async function apiRequest<T = unknown>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<ApiRequestResult<T>> {
  const {
    method = "GET",
    body,
    headers: extraHeaders,
    signal,
    backendUrl,
    getToken = getAccessToken,
    fetchImpl = fetch,
  } = options;

  const base = resolveBackendUrl(backendUrl);
  const url = joinUrl(base, path);

  const headers: Record<string, string> = {
    Accept: JSON_CONTENT_TYPE,
    ...(body !== undefined ? { "Content-Type": JSON_CONTENT_TYPE } : {}),
    ...extraHeaders,
  };

  const token = await getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetchImpl(url, {
      method,
      headers,
      body: body === undefined ? null : JSON.stringify(body),
      signal,
    });
  } catch (cause) {
    // The fetch itself failed before a response came back. Most common
    // causes: the backend is down, the emulator's host alias is wrong,
    // TLS handshake blew up, or the caller aborted. We expose ``network``
    // for all of them -- the caller cannot tell them apart from the
    // client side anyway, and React Query will retry transient ones.
    throw new ApiError({
      kind: "network",
      message: extractErrorMessage(cause, "Network request failed"),
      cause,
    });
  }

  const parsed = await parseBody(response);

  if (!response.ok) {
    const kind: ApiErrorKind = kindFromStatus(response.status);
    throw new ApiError({
      kind,
      status: response.status,
      message: messageFromBody(parsed, response.statusText) || defaultMessage(kind, response.status),
      body: parsed,
    });
  }

  return { status: response.status, body: parsed as T };
}

/**
 * Shorthand for ``apiRequest(path, { method: "GET" })``. The body is
 * returned directly so callers do not have to unpack the wrapper every time.
 */
export async function apiGet<T = unknown>(
  path: string,
  options: Omit<ApiRequestOptions, "method" | "body"> = {},
): Promise<T> {
  const result = await apiRequest<T>(path, { ...options, method: "GET" });
  return result.body;
}

export async function apiPost<T = unknown>(
  path: string,
  body?: unknown,
  options: Omit<ApiRequestOptions, "method" | "body"> = {},
): Promise<T> {
  const result = await apiRequest<T>(path, { ...options, method: "POST", body });
  return result.body;
}

export async function apiPut<T = unknown>(
  path: string,
  body?: unknown,
  options: Omit<ApiRequestOptions, "method" | "body"> = {},
): Promise<T> {
  const result = await apiRequest<T>(path, { ...options, method: "PUT", body });
  return result.body;
}

export async function apiPatch<T = unknown>(
  path: string,
  body?: unknown,
  options: Omit<ApiRequestOptions, "method" | "body"> = {},
): Promise<T> {
  const result = await apiRequest<T>(path, { ...options, method: "PATCH", body });
  return result.body;
}

export async function apiDelete<T = unknown>(
  path: string,
  options: Omit<ApiRequestOptions, "method" | "body"> = {},
): Promise<T> {
  const result = await apiRequest<T>(path, { ...options, method: "DELETE" });
  return result.body;
}

function joinUrl(base: string, path: string): string {
  const normalisedBase = base.replace(/\/+$/, "");
  const normalisedPath = path.startsWith("/") ? path : `/${path}`;
  return `${normalisedBase}${normalisedPath}`;
}

async function parseBody(response: Response): Promise<unknown> {
  // 204 has no body; reading it would throw ``Unexpected end of JSON input``.
  if (response.status === 204) return undefined;
  const text = await response.text();
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    // Non-JSON payload: surface it verbatim so the caller can still log it.
    return text;
  }
}

function messageFromBody(parsed: unknown, fallback: string): string | null {
  if (parsed && typeof parsed === "object" && "detail" in parsed) {
    const detail = (parsed as { detail: unknown }).detail;
    if (typeof detail === "string" && detail.length > 0) return detail;
    if (detail && typeof detail === "object") return JSON.stringify(detail);
  }
  return fallback || null;
}

function defaultMessage(kind: ApiErrorKind, status: number): string {
  switch (kind) {
    case "unauthorized":
      return status === 401
        ? "Your session has expired. Please sign in again."
        : "You are not allowed to perform this action.";
    case "notFound":
      return "The requested resource was not found.";
    case "clientError":
      return "The request was rejected.";
    case "server":
      return "The server encountered an error. Please try again.";
    default:
      return "Request failed.";
  }
}

function extractErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof Error && cause.message) return cause.message;
  return fallback;
}
