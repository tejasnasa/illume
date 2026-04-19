"use server";

import Repository from "@/types/repository";
import { headers } from "next/headers";

export async function getRepositories(): Promise<Repository[]> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch repository");

  const data = await res.json();

  return data;
}
