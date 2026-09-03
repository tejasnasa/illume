/**
 * Server action deleting a repository and returning to the dashboard.
 * @module DeleteRepoAction
 */

"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

/**
 * Deletes a repository owned by the caller.
 *
 * @param repoId - ID of the repository to delete.
 * @throws Error if the deletion fails.
 */
export default async function deleteRepoAction(repoId: string) {
  const cookieStore = await cookies();

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repoId}`,
    {
      method: "DELETE",
      headers: {
        Cookie: cookieStore.toString(),
      },
    },
  );

  if (!res.ok) {
    throw new Error("Failed to delete repository");
  }

  redirect("/dashboard");
}
