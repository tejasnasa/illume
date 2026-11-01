/**
 * Settings endpoints -- BYOK credentials, repository auto-update and sync,
 * the ``.illume`` export, the contact form, and the destructive repository
 * actions.
 *
 * @module SettingsApi
 *
 * The web client reaches these routes through Next.js server actions
 * (``client/src/actions/saveAiCredentials.ts`` and friends), which are thin
 * wrappers over the very same endpoints. A phone has no server, so the
 * routes are called directly.
 *
 * The routes are:
 *
 * - ``GET    /api/v1/auth/me/ai-credentials``   read the saved credential
 * - ``PUT    /api/v1/auth/me/ai-credentials``   probe and store a credential
 * - ``DELETE /api/v1/auth/me/ai-credentials``   clear the saved credential
 * - ``PATCH  /api/v1/repository/{id}/auto-update``  toggle / re-cadence
 * - ``POST   /api/v1/repository/{id}/sync``      queue a manual sync
 * - ``PUT    /api/v1/repository/{id}/reingest``  rebuild the analysis
 * - ``DELETE /api/v1/repository/{id}``           remove the repository
 * - ``GET    /api/v1/repository/{id}/export/illume``  the ``.illume`` bundle
 * - ``POST   /api/v1/contact``                   send a message
 *
 * The repository routes are keyed by the repository's **UUID**, not by the
 * user-scoped ``repo_number`` the dashboard links on.
 *
 * Every function takes an options bag so a test can inject a ``backendUrl``
 * and a ``fetchImpl`` rather than reaching for the global.
 */

import {
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  apiPut,
  type ApiRequestOptions,
} from "@/api/client";
import type Repository from "@/types/repository";

/**
 * Transport overrides a caller may inject.
 *
 * Production callers leave the bag empty and the shared client handles auth
 * and the base URL; tests supply a ``backendUrl`` and a ``fetchImpl``.
 */
export type SettingsRequestOptions = Omit<
  ApiRequestOptions,
  "method" | "body"
>;

/** The BYOK credential routes, relative to the backend base URL. */
const AI_CREDENTIALS_PATH = "/api/v1/auth/me/ai-credentials";

/** The public contact route, relative to the backend base URL. */
const CONTACT_PATH = "/api/v1/contact";

/**
 * The saved AI credential, as the server reports it.
 *
 * The key itself is never part of this payload -- the server stores it and
 * answers with the provider, the model, and whether a key is present. The
 * raw key lives only in the request that sets it.
 */
export interface AiCredentials {
  /** The provider key the credential belongs to, or ``null`` when unset. */
  provider: string | null;
  /** The model id the credential is paired with, or ``null`` when unset. */
  model: string | null;
  /** Whether a key is stored. The key itself is never returned. */
  has_key: boolean;
  /** When the key was last probed successfully, or ``null``. */
  validated_at: string | null;
}

/**
 * Body accepted by the credential-saving endpoint.
 *
 * The field is ``api_key`` because that is the server's spelling; the form
 * calls it ``apiKey`` and the transport renames it.
 */
export interface SaveAiCredentialsPayload {
  /** The provider key, e.g. ``openai``. */
  provider: string;
  /** The raw API key, as pasted by the user. */
  api_key: string;
  /** The model id to use with the credential. */
  model: string;
}

/**
 * Body accepted by the auto-update endpoint.
 *
 * Both fields are optional: omitting one leaves that setting alone.
 */
export interface AutoUpdatePayload {
  /** Turn auto-update on or off. Omitted leaves the current value alone. */
  enabled?: boolean;
  /** The new cadence, in hours. One of 1, 3, 6, 12 or 24. */
  interval_hours?: number;
}

/**
 * Body accepted by the re-ingest endpoint.
 *
 * Both fields narrow the ingest to a specific snapshot; omitting both
 * re-ingests the repository's default branch tip.
 */
export interface ReingestPayload {
  /** Branch to re-ingest. ``null`` means the default branch. */
  branch?: string | null;
  /** Commit SHA to pin the ingest to. ``null`` means the branch tip. */
  commit_sha?: string | null;
}

/**
 * What the sync endpoint answers.
 *
 * ``sync_status`` becomes ``queued`` on a successful request; the worker
 * moves it on from there.
 */
export interface SyncResponse {
  /** The repository the sync was queued for. */
  repo_id: string;
  /** The repository's sync status right after the request. */
  sync_status: string;
  /** When the next sweep will look at the repository. */
  next_sync_at: string | null;
}

/**
 * What the re-ingest endpoint answers.
 */
export interface ReingestResponse {
  /** The repository's id -- the same id the row was recreated with. */
  repo_id: string;
  /** The repository's user-scoped number. */
  repo_num: number;
}

/**
 * One contact-form submission.
 *
 * ``illume_hp`` is the honeypot: a decoy field an automated submitter
 * fills because it posts every input it parses. The server discards a
 * submission that carries a value and answers exactly as though it had
 * been delivered, so a bot learns nothing from the outcome.
 */
export interface ContactPayload {
  /** The category slug: ``bug``, ``feature``, ``question`` or ``other``. */
  category: string;
  /** The sender's name. */
  name: string;
  /** The sender's email address. */
  email: string;
  /** The message body. */
  message: string;
  /** The honeypot value. Always empty for a human. */
  illume_hp: string;
}

/**
 * The contact endpoint's success envelope.
 */
export interface ContactResponse {
  /** The operator's confirmation message. */
  message: string;
}

/**
 * Build the path of a repository's settings routes.
 *
 * @param repoId - The repository's UUID.
 * @returns The absolute API path.
 */
function repositoryPath(repoId: string): string {
  return `/api/v1/repository/${repoId}`;
}

/**
 * Read the caller's saved AI credential.
 *
 * Always answers 200 -- even with no credential stored -- so the settings
 * screen can render the unconfigured state without a second request to tell
 * "no key" from "not signed in".
 *
 * @param options - Test-friendly transport overrides.
 * @returns The provider, model and ``has_key`` flag. Never the key itself.
 */
export function getAiCredentials(
  options: SettingsRequestOptions = {},
): Promise<AiCredentials> {
  return apiGet<AiCredentials>(AI_CREDENTIALS_PATH, options);
}

/**
 * Save (or replace) the caller's AI credential.
 *
 * The backend probes the key before writing anything, so a successful
 * response means the credential was validated.
 *
 * @param payload - The provider, raw key and model to store.
 * @param options - Test-friendly transport overrides.
 * @returns The stored credential, in the same shape as the read.
 */
export function saveAiCredentials(
  payload: SaveAiCredentialsPayload,
  options: SettingsRequestOptions = {},
): Promise<AiCredentials> {
  return apiPut<AiCredentials>(AI_CREDENTIALS_PATH, payload, options);
}

/**
 * Clear the caller's saved AI credential.
 *
 * The free-tier counters are not restored -- removing a key does not give
 * the allowance back.
 *
 * @param options - Test-friendly transport overrides.
 * @returns The cleared credential envelope.
 */
export function removeAiCredentials(
  options: SettingsRequestOptions = {},
): Promise<AiCredentials> {
  return apiDelete<AiCredentials>(AI_CREDENTIALS_PATH, options);
}

/**
 * Turn auto-update on or off, and change the sync cadence.
 *
 * @param repoId - The repository's UUID.
 * @param payload - The settings to change. Omitted fields stay as they are.
 * @param options - Test-friendly transport overrides.
 * @returns The updated repository.
 */
export function updateAutoUpdate(
  repoId: string,
  payload: AutoUpdatePayload,
  options: SettingsRequestOptions = {},
): Promise<Repository> {
  return apiPatch<Repository>(
    `${repositoryPath(repoId)}/auto-update`,
    payload,
    options,
  );
}

/**
 * Queue a manual sync for a repository.
 *
 * The endpoint answers 409 when a sync is already in flight, and 409 when
 * the repository has no baseline commit to diff against -- both are normal
 * outcomes whose message the caller should show.
 *
 * @param repoId - The repository's UUID.
 * @param options - Test-friendly transport overrides.
 * @returns The repository's new sync status.
 */
export function triggerSync(
  repoId: string,
  options: SettingsRequestOptions = {},
): Promise<SyncResponse> {
  return apiPost<SyncResponse>(`${repositoryPath(repoId)}/sync`, undefined, options);
}

/**
 * Re-ingest a repository from scratch.
 *
 * The endpoint deletes the repository row and recreates it with the same
 * id, which cascades every child row away with it.
 *
 * @param repoId - The repository's UUID.
 * @param payload - The version to ingest. Omitted re-ingests the tip.
 * @param options - Test-friendly transport overrides.
 * @returns The recreated repository's identifiers.
 */
export function reingestRepository(
  repoId: string,
  payload?: ReingestPayload,
  options: SettingsRequestOptions = {},
): Promise<ReingestResponse> {
  return apiPut<ReingestResponse>(
    `${repositoryPath(repoId)}/reingest`,
    payload,
    options,
  );
}

/**
 * Delete a repository and everything hanging off it.
 *
 * @param repoId - The repository's UUID.
 * @param options - Test-friendly transport overrides.
 * @returns Nothing; the endpoint answers 204.
 */
export function deleteRepository(
  repoId: string,
  options: SettingsRequestOptions = {},
): Promise<void> {
  return apiDelete<void>(repositoryPath(repoId), options);
}

/**
 * Download a repository's ``.illume`` bundle.
 *
 * The endpoint answers with plain text, not JSON. The shared client falls
 * back to the raw body when it cannot be parsed as JSON, which is exactly
 * what this route produces.
 *
 * @param repoId - The repository's UUID.
 * @param options - Test-friendly transport overrides.
 * @returns The bundle's text.
 */
export function exportRepositoryIllume(
  repoId: string,
  options: SettingsRequestOptions = {},
): Promise<string> {
  return apiGet<string>(`${repositoryPath(repoId)}/export/illume`, options);
}

/**
 * Send a contact-form submission.
 *
 * The endpoint is public, so it answers the same way whether or not the
 * caller is signed in.
 *
 * @param payload - The submission to send.
 * @param options - Test-friendly transport overrides.
 * @returns The operator's confirmation message.
 */
export function submitContact(
  payload: ContactPayload,
  options: SettingsRequestOptions = {},
): Promise<ContactResponse> {
  return apiPost<ContactResponse>(CONTACT_PATH, payload, options);
}
