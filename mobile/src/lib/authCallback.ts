/**
 * Parse the URL the OAuth callback redirects to.
 *
 * Pure functions over a URL or string, no React, no native modules -- the
 * whole point is that this module is unit-testable without a device. The
 * callback screen uses :func:`extractTokenFromUrl` to lift the token out of
 * the deep link and :func:`buildAuthorizeUrl` for the inverse direction.
 *
 * Implementation note: the parser does not rely on ``URL`` /
 * ``URLSearchParams`` because the React Native runtime's polyfills have
 * surprised us before. Manual parsing handles the common OAuth shapes and
 * is unit-testable without `URL` being a global.
 */

interface AuthCallbackPayload {
  /** The bearer token returned by the backend, when present and non-empty. */
  token: string | null;
  /** Token type, e.g. ``Bearer``; ``null`` when the response carried no token. */
  tokenType: string | null;
  /** Token lifetime in seconds, if the backend advertised one. ``null`` otherwise. */
  expiresIn: number | null;
  /** Errors reported by the backend. Used to surface a human-readable message. */
  error: string | null;
}

/**
 * Extract the auth payload from a URL the deep-link handler has received.
 *
 * The backend redirects to ``illume://auth/callback?access_token=…&token_type=Bearer&expires_in=…``
 * on success, or ``illume://auth/callback?error=…`` on failure. Accepting
 * either the full URL or just the query lets us test the parser without
 * building a URL object.
 */
export function parseAuthCallback(input: string | URL): AuthCallbackPayload {
  const params = queryStringToParams(extractQueryString(input));
  const error =
    firstString(params.error) ?? firstString(params.error_description) ?? null;
  const token = firstString(params.access_token);
  const tokenType = firstString(params.token_type);
  const expiresRaw = firstString(params.expires_in);
  const expiresIn =
    expiresRaw && /^\d+$/.test(expiresRaw) ? Number(expiresRaw) : null;

  return {
    token: token && token.length > 0 ? token : null,
    tokenType: tokenType && tokenType.length > 0 ? tokenType : null,
    expiresIn,
    error,
  };
}

function extractQueryString(input: string | URL): string {
  if (typeof input === "string") {
    // Match ``?...`` if present. The most permissive pattern works for
    // ``scheme://host/path?a=b``, ``/path?a=b``, or just ``?a=b``.
    const match = input.match(/^[^?]*(?:\?(.*))?$/);
    return match?.[1] ?? "";
  }
  const raw = input.search ?? "";
  return raw.startsWith("?") ? raw.slice(1) : raw;
}

/**
 * Parse a query string into a record of string-or-string-array values.
 *
 * Values are percent-decoded by hand (no reliance on a global polyfill).
 * The implementation accepts the small subset of percent-encoding that
 * appears in OAuth callbacks (encoded characters in keys/values, ``+`` as
 * a literal plus sign, no nested arrays beyond the simple ``&`` repeat).
 */
function queryStringToParams(query: string): Record<string, string | string[]> {
  if (!query) return {};
  const out: Record<string, string | string[]> = {};
  for (const pair of query.split("&")) {
    if (!pair) continue;
    const eq = pair.indexOf("=");
    const rawKey = eq === -1 ? pair : pair.slice(0, eq);
    const rawValue = eq === -1 ? "" : pair.slice(eq + 1);
    const key = decode(rawKey);
    const value = decode(rawValue);
    if (key in out) {
      const existing = out[key];
      out[key] = Array.isArray(existing)
        ? [...existing, value]
        : [existing, value];
    } else {
      out[key] = value;
    }
  }
  return out;
}

function decode(input: string): string {
  if (!input) return input;
  // OAuth error strings are form-encoded (``+`` means space); OAuth tokens
  // are base64-url, which never contains ``+`` to begin with. Replace
  // ``+`` first because ``decodeURIComponent`` leaves it literal.
  const withSpaces = input.replace(/\+/g, " ");
  try {
    return decodeURIComponent(withSpaces);
  } catch {
    return withSpaces;
  }
}

function firstString(value: string | string[] | undefined): string | null {
  if (value === undefined) return null;
  const first = Array.isArray(value) ? value[0] : value;
  return first ?? null;
}

/**
 * Build the URL the login screen opens in the system browser.
 *
 * The state parameter carries the deep link on the allowlist; the backend
 * echoes it back and decides whether to honour it.
 */
export function buildAuthorizeUrl(
  backendUrl: string,
  deepLinkState: string,
): string {
  const base = backendUrl.replace(/\/+$/, "");
  const search = new URLSearchParams({ state: deepLinkState });
  return `${base}/api/v1/auth/github?${search.toString()}`;
}

export type { AuthCallbackPayload };
