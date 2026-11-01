/**
 * The push notification registration endpoints.
 *
 * @module pushApi
 *
 * A device registers itself with the backend once, and the backend keeps
 * the token so it can reach the device when an ingest finishes. The token
 * is removed again when the device signs out.
 */

import { apiRequest, type ApiRequestOptions } from "@/api/client";
import type PushTokenStatus from "@/types/push";

type TestOptions = Omit<ApiRequestOptions, "method" | "body">;

/**
 * Register this device for push notifications.
 *
 * @param token - The Expo push token.
 * @param platform - Which platform the device is.
 * @param options - Test seam for the base URL and the fetch implementation.
 * @returns Whether the user now has a registered device, and how many.
 */
export function registerPushToken(
  token: string,
  platform: "android" | "ios",
  options: TestOptions = {},
): Promise<PushTokenStatus> {
  return apiRequest<PushTokenStatus>("/api/v1/push/token", {
    ...options,
    method: "POST",
    body: { token, platform },
  }).then((result) => result.body);
}

/**
 * Remove this device from the push registry.
 *
 * @param token - The Expo push token to remove.
 * @param options - Test seam for the base URL and the fetch implementation.
 * @returns Whether the user still has a registered device, and how many.
 */
export function deregisterPushToken(
  token: string,
  options: TestOptions = {},
): Promise<PushTokenStatus> {
  return apiRequest<PushTokenStatus>("/api/v1/push/token", {
    ...options,
    method: "DELETE",
    body: { token },
  }).then((result) => result.body);
}

/**
 * Whether the signed-in user has a device registered for push.
 *
 * @param options - Test seam for the base URL and the fetch implementation.
 * @returns The registration status.
 */
export function getPushTokenStatus(
  options: TestOptions = {},
): Promise<PushTokenStatus> {
  return apiRequest<PushTokenStatus>("/api/v1/push/token", {
    ...options,
    method: "GET",
  }).then((result) => result.body);
}
