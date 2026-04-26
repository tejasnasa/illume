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

  if (!res.ok) throw new Error("Failed to fetch repositories");

  const data = await res.json();

  return data;
}

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
