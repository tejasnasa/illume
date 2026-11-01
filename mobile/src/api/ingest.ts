/**
 * The live ingestion WebSocket.
 *
 * @module ingestApi
 *
 * The backend's ingest stream is a plain WebSocket at
 * ``/api/v1/ws/ingest/{repo_id}``. It is the one endpoint the app reaches
 * that is not a REST call, so it gets its own module rather than living in
 * :mod:`src.api.client` -- that module is a ``fetch`` wrapper, and a socket
 * is not a fetch.
 *
 * The token travels as a query parameter. That is the backend's own
 * convention (the endpoint accepts ``?token=`` as an alternative to the
 * httponly cookie, for clients that cannot send one), and React Native has
 * no cookie jar, so the query parameter is the only option here. The
 * downside is the same one the web client has: the token lands in access
 * logs.
 */

import { resolveBackendUrl } from "@/api/client";

/**
 * Build the WebSocket URL for a repository's ingestion channel.
 *
 * The backend URL's scheme is swapped for its WebSocket equivalent -- ``http``
 * to ``ws``, ``https`` to ``wss`` -- which is what makes a production build
 * work over TLS without a second environment variable.
 *
 * @param repoId - The repository's UUID. Not its user-scoped number: the
 *   WebSocket route is typed as a UUID.
 * @param token - The bearer token.
 * @param backendUrl - Override for the backend base URL. Used by tests.
 * @returns The absolute WebSocket URL.
 */
export function ingestSocketUrl(
  repoId: string,
  token: string,
  backendUrl?: string,
): string {
  const base = resolveBackendUrl(backendUrl).replace(/^http/, "ws");
  return `${base}/api/v1/ws/ingest/${repoId}?token=${encodeURIComponent(token)}`;
}
