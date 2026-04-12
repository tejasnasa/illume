"use server";

import { redirect } from "next/navigation";

export default async function logoutAction() {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/auth/logout`,
    {
      method: "POST",
      credentials: "include",
    },
  );

  if (!res.ok) {
    throw new Error("Failed to logout");
  }

  redirect("/login");
}
