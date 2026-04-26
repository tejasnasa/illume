"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export default async function regenerateRepoAction(repoId: string) {
  const cookieStore = await cookies();

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repoId}/reingest`,
    {
      method: "PUT",
      headers: {
        Cookie: cookieStore.toString(),
      },
    },
  );

  if (!res.ok) {
    throw new Error("Failed to regenerate repository");
  }

  redirect("/dashboard");
}
