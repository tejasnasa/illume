/**
 * Authenticated-user fetch for server components.
 * @module AuthApi
 */

import User from "@/types/user";
import { headers } from "next/headers";

/**
 * Fetches the current user's profile from the backend.
 *
 * Forwards the incoming request cookies so the backend session is preserved.
 * @returns The authenticated user's profile.
 * @throws Error if the request fails (e.g. unauthenticated).
 */
export default async function GetMyData(): Promise<User> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/auth/me`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch my data");

  const data = await res.json();

  return data;
}
