/**
 * Typed errors raised by :mod:`src.api.client`.
 *
 * Every failure the API client surfaces becomes an :class:`ApiError` so
 * downstream code can branch on ``kind`` instead of parsing a free-form
 * message string. The discriminator matches what the backend returns on
 * common paths -- a 401 means ``unauthorized``, 404 means ``notFound``,
 * anything 5xx is ``server``, and a fetch that never resolved (DNS, TCP,
 * abort) is ``network``. Anything we did not anticipate collapses to
 * ``unknown`` rather than being silently rethrown as the underlying error.
 */

export type ApiErrorKind =
  /** Server returned 401 or 403; the caller is not signed in or the token is stale. */
  | "unauthorized"
  /** Server returned 404; the resource does not exist (or is not owned by the caller). */
  | "notFound"
  /**
   * Server returned 402; the caller has run out of free-tier allowance.
   *
   * Distinct from a generic 4xx because the remedy is different: the
   * user has to add their own API key, not fix their request.
   */
  | "quota"
  /** Server returned any other 4xx. The caller generally should surface the message. */
  | "clientError"
  /** Server returned 5xx. Almost always transient. */
  | "server"
  /** The request never produced a response -- DNS failure, TCP reset, TLS error, timeout. */
  | "network"
  /** Anything we did not classify. Carries ``cause`` for debugging. */
  | "unknown";

/**
 * Single error type thrown by :func:`apiRequest`.
 *
 * Subclasses ``Error`` so React Query treats it like any thrown error (it
 * populates the ``error`` slot on the query), while still letting consumers
 * narrow on :attr:`ApiErrorKind` for control flow.
 */
export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  /** HTTP status code when one was received; ``undefined`` for network / parse failures. */
  readonly status: number | undefined;
  /** Raw response payload (parsed JSON or a string) for diagnostic surfacing. */
  readonly body: unknown;
  /** The underlying error when the failure happened before a response came back. */
  readonly cause: unknown;

  constructor(options: {
    kind: ApiErrorKind;
    message: string;
    status?: number;
    body?: unknown;
    cause?: unknown;
  }) {
    super(options.message);
    this.name = "ApiError";
    this.kind = options.kind;
    this.status = options.status;
    this.body = options.body;
    this.cause = options.cause;
  }
}

/**
 * Classify an HTTP status into an :class:`ApiErrorKind`.
 *
 * Splitting on the 4xx/5xx boundary keeps the discriminators coarse enough
 * that callers do not need a switch for every code, but specific enough
 * that ``unauthorized`` and ``notFound`` are first-class cases -- they are
 * the two the UI cares about (one redirects to /login, the other shows an
 * empty card).
 */
export function kindFromStatus(status: number): ApiErrorKind {
  if (status === 401 || status === 403) return "unauthorized";
  if (status === 404) return "notFound";
  if (status === 402) return "quota";
  if (status >= 400 && status < 500) return "clientError";
  if (status >= 500) return "server";
  return "unknown";
}
