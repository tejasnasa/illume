/**
 * Server action re-ingesting a repository and returning to the dashboard.
 * @module RegenerateRepoAction
 */

"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

/**
 * Re-runs full ingestion for a finished repository.
 *
 * @param repoId - ID of the repository to re-ingest.
 * @throws Error if re-ingestion cannot start (e.g. still in progress).
 */
export default async function regenerateRepoAction(repoId: string) {
  const cookieStore = await cookies();

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repoId}/reingest`,
    {
      method: "PUT",
      headers: {
        Cookie: cookieStore.toString(),
      },
    },
  );

  if (!res.ok) {
    throw new Error("Failed to regenerate repository");
  }

  redirect("/dashboard");
}
