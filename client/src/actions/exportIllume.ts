/**
 * Server action exporting a ready repository as a `.illume` bundle.
 * @module ExportIllumeAction
 */

"use server";

import { cookies } from "next/headers";

/**
 * Downloads the `.illume` bundle text for a ready repository.
 *
 * @param repoId - ID of the repository to export.
 * @returns Plain-text bundle content for client-side download.
 * @throws Error if the export fails (e.g. ingestion incomplete).
 */
export async function exportIllumeAction(repoId: string): Promise<string> {
  const cookieStore = await cookies();

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repoId}/export/illume`,
    {
      method: "GET",
      headers: {
        Cookie: cookieStore.toString(),
      },
      cache: "no-store",
    },
  );

  if (!res.ok) {
    throw new Error("Failed to export repository data");
  }

  return await res.text();
}
