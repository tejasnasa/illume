/**
 * Server action saving the agent settings for the current user.
 * @module SaveAgentSettingsAction
 */

"use server";

import { cookies } from "next/headers";

/**
 * Payload accepted by the PUT /me/agent-settings endpoint.
 */
export type SaveAgentSettingsPayload = {
  /** Input tokens one model call may carry; null resets to the default. */
  contextWindow: number | null;
};

/**
 * Saves the user's agent settings. Separate from the AI credential, so a
 * change here never asks for the key again. The backend rejects a window
 * outside its bounds (422); this helper surfaces the message so the form can
 * render it inline.
 *
 * @param payload - The settings to save.
 * @throws Error when the backend rejects the save.
 */
export default async function saveAgentSettingsAction(
  payload: SaveAgentSettingsPayload,
) {
  const cookieStore = await cookies();

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/auth/me/agent-settings`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Cookie: cookieStore.toString(),
      },
      body: JSON.stringify({ context_window: payload.contextWindow }),
    },
  );

  if (!res.ok) {
    let detail = "Failed to save agent settings";
    try {
      const err = await res.json();
      // A validation error carries a list; anything else a string.
      detail = typeof err.detail === "string" ? err.detail : detail;
    } catch {
      // Body was not JSON; fall back to the generic message.
    }
    throw new Error(detail);
  }
}
