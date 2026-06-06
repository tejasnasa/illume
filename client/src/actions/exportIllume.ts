"use server";

import { cookies } from "next/headers";

export async function exportIllumeAction(repoId: string): Promise<string> {
  const cookieStore = await cookies();

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repoId}/export/illume`,
    {
      method: "GET",
      headers: {
        Cookie: cookieStore.toString(),
      },
      cache: "no-store",
    },
  );

  if (!res.ok) {
    throw new Error("Failed to export repository data");
  }

  return await res.text();
}
