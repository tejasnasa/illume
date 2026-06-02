"use client";

import { useRouter } from "next/navigation";

export function useLogout() {
  const router = useRouter();

  async function logout() {
    await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
    router.push("/login");
  }

  return logout;
}
