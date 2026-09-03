/**
 * Dependency graph fetch (server action).
 * @module GraphApi
 */

"use server";

import Graph from "@/types/graph";
import { headers } from "next/headers";

/**
 * Builds the dependency graph JSON for visualization.
 *
 * @param repoId - ID of the repository to visualize.
 * @param level - Graph granularity, either file-level or symbol-level.
 * @returns Graph payload with nodes, edges, and metadata.
 * @throws Error if the fetch fails.
 */
export async function getRepoGraph(
  repoId: string,
  level: "file" | "symbol",
): Promise<Graph> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repoId}/graph?level=${level}`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch repository");

  const data = await res.json();

  return data;
}
