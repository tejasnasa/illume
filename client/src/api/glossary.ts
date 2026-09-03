/**
 * Glossary browsing and search fetches.
 * @module GlossaryApi
 */

import Glossary from "@/types/glossary";
import { headers } from "next/headers";

/**
 * Browses glossary entries alphabetically with pagination.
 *
 * @param id - ID of the repository whose glossary to browse.
 * @param page - 1-indexed page number.
 * @param page_size - Entries per page.
 * @returns Paginated entries plus total count.
 * @throws Error if the fetch fails.
 */
export async function GetGlossary(
  id: string,
  page: number,
  page_size: number,
): Promise<Glossary> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${id}/glossary?page=${page}&page_size=${page_size}`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch repo glossary");

  const data = await res.json();

  return data;
}

/**
 * Searches glossary entries by name or definition substring.
 *
 * @param id - ID of the repository whose glossary to search.
 * @param q - Case-insensitive substring; encoded to survive special characters.
 * @param page - 1-indexed page number.
 * @param page_size - Entries per page.
 * @returns Paginated matching entries plus total count.
 * @throws Error if the fetch fails.
 */
export async function GetGlossarySearchResults(
  id: string,
  q: string,
  page: number,
  page_size: number,
): Promise<Glossary> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${id}/glossary?q=${encodeURIComponent(q)}&page=${page}&page_size=${page_size}`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch repo glossary");

  const data = await res.json();

  return data;
}
