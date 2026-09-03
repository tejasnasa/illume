/**
 * Repository listing and detail fetches (server actions).
 * @module RepositoryApi
 */

"use server";

import Repository from "@/types/repository";
import { headers } from "next/headers";

/**
 * Lists the caller's repositories, newest first.
 *
 * @returns The user's repositories with truncated summaries.
 * @throws Error if the fetch fails.
 */
export async function getRepositories(): Promise<Repository[]> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch repositories");

  const data = await res.json();

  return data;
}

/**
 * Fetches one repository by its user-scoped repo number.
 *
 * @param id - Human-friendly per-user repository number.
 * @returns The matching repository.
 * @throws Error if the repository is not found.
 */
export async function GetRepository(id: number): Promise<Repository> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${id}`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error(`Repository not found: ${res.status}`);

  const data = await res.json();

  return data;
}
