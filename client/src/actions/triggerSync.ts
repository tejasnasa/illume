/**
 * Server action requesting an immediate background sync for a repository.
 * @module TriggerSyncAction
 */

"use server";

import { cookies } from "next/headers";

/**
 * Kicks off a sync for the given repository right now.
 *
 * The backend returns 409 when a sync is already in flight (an unexpired
 * `sync_lease_expires_at`). The caller surfaces that to the user; this helper
 * preserves the response shape so the UI can read it.
 *
 * @param repoId - ID of the repository to sync.
 * @returns Object describing the queued sync.
 * @throws Error if the backend refuses the request.
 */
export default async function triggerSyncAction(repoId: string) {
  const cookieStore = await cookies();

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repoId}/sync`,
    {
      method: "POST",
      headers: {
        Cookie: cookieStore.toString(),
      },
    },
  );

  if (!res.ok) {
    let detail = "Failed to queue sync";
    try {
      const err = await res.json();
      detail = err.detail ?? detail;
    } catch {
      // Body was not JSON; fall back to the generic message.
    }
    throw new Error(detail);
  }

  return (await res.json()) as {
    repo_id: string;
    sync_status: string;
    next_sync_at: string | null;
  };
}
