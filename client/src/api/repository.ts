"use server";

import { headers } from "next/headers";

interface Repository {
  id: number;
  name: string;
  description: string;
  updatedAt: string;
  github_url: string;
  status: string;
}

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
