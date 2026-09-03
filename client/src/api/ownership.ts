/**
 * Code ownership map and knowledge-silo fetches (server actions).
 * @module OwnershipApi
 */

"use server";
import Ownership, { Silo } from "@/types/ownership";
import { headers } from "next/headers";

/**
 * Lists per-file ownership ordered by path, with pagination.
 *
 * @param id - ID of the repository whose ownership map to list.
 * @param page - 1-indexed page number.
 * @param page_size - Entries per page.
 * @param filePath - Optional exact file-path filter, encoded when present.
 * @returns Paginated ownership entries plus total count.
 * @throws Error if the fetch fails.
 */
export async function GetOwnership(
  id: string,
  page: number,
  page_size: number,
  filePath?: string,
): Promise<Ownership> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${id}/ownership?page=${page}&page_size=${page_size}${filePath ? `&file_path=${encodeURIComponent(filePath)}` : ""}`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch repo ownership");

  const data = await res.json();

  return data;
}

/**
 * Lists files flagged as knowledge silos (bus factor of one).
 *
 * @param id - ID of the repository whose silos to list.
 * @param page - 1-indexed page number.
 * @param page_size - Entries per page.
 * @returns All silo files plus total count.
 * @throws Error if the fetch fails.
 */
export async function GetOwnershipSilos(
  id: string,
  page: number,
  page_size: number,
): Promise<Silo> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${id}/ownership/silos?page=${page}&page_size=${page_size}`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch repo ownership");

  const data = await res.json();

  return data;
}
