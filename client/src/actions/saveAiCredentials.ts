/**
 * Server action saving the BYOK AI credentials for the current user.
 * @module SaveAiCredentialsAction
 */

"use server";

import { cookies } from "next/headers";

/**
 * Payload accepted by the PUT /me/ai-credentials endpoint.
 */
export type SaveAiCredentialsPayload = {
  provider: string;
  apiKey: string;
  model: string;
};

/**
 * Saves the user's BYOK AI provider, key, and model after the backend probes
 * the key for validity. The backend rejects unknown providers (422) and an
 * incompatible key/model/reasoning combination (400) -- this helper surfaces
 * the backend's `detail` message so the form can render it inline.
 *
 * @param payload - The provider key name, plaintext API key, and model id.
 * @throws Error when the backend rejects the save (invalid key, unknown
 *         provider, etc.). The message is the backend's `detail`.
 */
export default async function saveAiCredentialsAction(
  payload: SaveAiCredentialsPayload,
) {
  const { provider, apiKey, model } = payload;
  const cookieStore = await cookies();

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/auth/me/ai-credentials`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Cookie: cookieStore.toString(),
      },
      body: JSON.stringify({
        provider,
        api_key: apiKey,
        model,
      }),
    },
  );

  if (!res.ok) {
    let detail = "Failed to save AI credentials";
    try {
      const err = await res.json();
      detail = err.detail ?? detail;
    } catch {
      // Body was not JSON; fall back to the generic message.
    }
    throw new Error(detail);
  }
}
