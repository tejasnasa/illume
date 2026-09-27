/**
 * Server action requesting an immediate background sync for a repository.
 * @module TriggerSyncAction
 */

"use server";

import { cookies } from "next/headers";

/**
 * Outcome of a sync request.
 *
 * Failures are *returned*, never thrown. Next.js replaces the message of an
 * error thrown out of a Server Action with a generic "an error occurred in the
 * Server Components render" string in production, so the backend's explanation
 * -- the whole point of a 409 here -- would never reach the browser. A return
 * value crosses that boundary intact.
 */
export type TriggerSyncResult =
  | { ok: true; sync_status: string; next_sync_at: string | null }
  | { ok: false; detail: string };

/**
 * Kicks off a sync for the given repository right now.
 *
 * The backend answers 409 when the repository has no baseline commit to diff
 * against, or when a sync is already in flight (an unexpired
 * `sync_lease_expires_at`). Both carry a `detail` worth showing.
 *
 * @param repoId - ID of the repository to sync.
 * @returns The queued sync's status, or the backend's reason for refusing.
 */
export default async function triggerSyncAction(
  repoId: string,
): Promise<TriggerSyncResult> {
  const cookieStore = await cookies();

  let res: Response;
  try {
    res = await fetch(
      `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repoId}/sync`,
      {
        method: "POST",
        headers: {
          Cookie: cookieStore.toString(),
        },
      },
    );
  } catch {
    // The fetch itself failed -- the backend was unreachable rather than
    // unwilling. Distinct from a refusal, and worth its own wording.
    return { ok: false, detail: "Could not reach the server. Try again." };
  }

  if (!res.ok) {
    let detail = "Failed to queue sync";
    try {
      const err = await res.json();
      detail = err.detail ?? detail;
    } catch {
      // Body was not JSON; fall back to the generic message.
    }
    return { ok: false, detail };
  }

  const data = (await res.json()) as {
    repo_id: string;
    sync_status: string;
    next_sync_at: string | null;
  };

  return {
    ok: true,
    sync_status: data.sync_status,
    next_sync_at: data.next_sync_at,
  };
}
