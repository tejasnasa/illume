/**
 * Onboarding guide and stats fetches.
 * @module GuideApi
 */

import Guide, { Stats } from "@/types/guide";
import { headers } from "next/headers";

/**
 * Fetches the parsed onboarding guide for a repository.
 *
 * @param id - ID of the repository whose guide to fetch.
 * @returns Reading order, critical files, and architecture brief.
 * @throws Error if the fetch fails.
 */
export async function GetGuide(id: string): Promise<Guide> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${id}/guide`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch repo guide");

  const data = await res.json();

  return data;
}

/**
 * Fetches aggregated dashboard stats for a repository.
 *
 * @param id - ID of the repository to summarize.
 * @returns Totals plus language breakdown and top contributors.
 * @throws Error if the fetch fails.
 */
export async function GetGuideStats(id: string): Promise<Stats> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${id}/stats`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch repo stats");

  const data = await res.json();

  return data;
}
