"use server";

import Graph from "@/types/graph";
import { headers } from "next/headers";

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

  if (!res.ok) throw new Error("Failed to fetch repositories");

  const data = await res.json();

  return data;
}
