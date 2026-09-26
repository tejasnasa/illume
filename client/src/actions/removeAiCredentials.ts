/**
 * Server action clearing the BYOK AI credentials for the current user.
 * @module RemoveAiCredentialsAction
 */

"use server";

import { cookies } from "next/headers";

/**
 * Deletes the user's saved BYOK credentials. The backend removes the provider,
 * key, model and validated-at timestamp; the free allowance is not restored.
 *
 * @throws Error when the backend refuses the delete (rare -- typically only
 *         an auth failure). The message is the backend's `detail`.
 */
export default async function removeAiCredentialsAction() {
  const cookieStore = await cookies();

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/auth/me/ai-credentials`,
    {
      method: "DELETE",
      headers: {
        Cookie: cookieStore.toString(),
      },
    },
  );

  if (!res.ok) {
    let detail = "Failed to remove AI credentials";
    try {
      const err = await res.json();
      detail = err.detail ?? detail;
    } catch {
      // Body was not JSON; fall back to the generic message.
    }
    throw new Error(detail);
  }
}
