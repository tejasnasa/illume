/**
 * Server action toggling auto-update and the sync interval for a repository.
 * @module UpdateAutoUpdateAction
 */

"use server";

import { cookies } from "next/headers";

/**
 * Payload for the auto-update PATCH endpoint.
 */
type UpdateAutoUpdatePayload = {
  repoId: string;
  enabled?: boolean;
  intervalHours?: number;
};

/**
 * Enables or disables auto-update, or changes the sync cadence, for a repository.
 *
 * The backend treats `undefined` fields as "leave alone", so this helper does too.
 * At least one of `enabled` / `intervalHours` should be supplied -- sending neither
 * is a no-op that wastes a round trip.
 *
 * @param payload - Repo id plus the fields to update.
 * @throws Error when the backend rejects the update (e.g. invalid interval).
 */
export default async function updateAutoUpdateAction(
  payload: UpdateAutoUpdatePayload,
) {
  const { repoId, enabled, intervalHours } = payload;
  const cookieStore = await cookies();

  const body: Record<string, unknown> = {};
  if (enabled !== undefined) body.enabled = enabled;
  if (intervalHours !== undefined) body.interval_hours = intervalHours;

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repoId}/auto-update`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Cookie: cookieStore.toString(),
      },
      body: JSON.stringify(body),
    },
  );

  if (!res.ok) {
    let detail = "Failed to update auto-update settings";
    try {
      const err = await res.json();
      detail = err.detail ?? detail;
    } catch {
      // Body was not JSON; fall back to the generic message.
    }
    throw new Error(detail);
  }
}
