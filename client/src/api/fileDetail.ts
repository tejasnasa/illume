/**
 * Per-file symbols and history fetch (server action).
 * @module FileDetailApi
 */

"use server";
import { FileDetail } from "@/types/explorer";
import { headers } from "next/headers";

/**
 * Fetches a file's definitions and the latest commits that touched it.
 *
 * @param id - ID of the repository the file belongs to.
 * @param path - Repository-relative file path.
 * @returns The file's symbols and recent commits.
 * @throws Error if the fetch fails.
 */
export async function GetFileDetail(id: string, path: string): Promise<FileDetail> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${id}/file?path=${encodeURIComponent(path)}`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch file detail");

  return res.json();
}
