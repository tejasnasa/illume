/**
 * Logout action clearing the session and returning to login.
 * @module UseLogout
 */

"use client";

import { useRouter } from "next/navigation";

/**
 * Provides a logout callback that clears the session cookie.
 *
 * @returns Async logout function redirecting to the login page.
 */
export function useLogout() {
  const router = useRouter();

  /**
   * Clears the backend session, then navigates to login.
   */
  async function logout() {
    await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
    router.push("/login");
  }

  return logout;
}
