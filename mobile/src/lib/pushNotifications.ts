/**
 * The platform side of push notifications.
 *
 * @module pushNotifications
 *
 * `expo-notifications` is loaded lazily rather than imported at the top of
 * the module. Remote push does not work in Expo Go, and importing the
 * package there can crash the app on Android -- so a build that has no
 * push support must not even load the module until a push is actually
 * wanted.
 *
 * Everything here is a thin wrapper over the Expo API. The decisions --
 * when to ask, when to register -- live in the hook that uses it.
 */

import { Platform } from "react-native";

/** The platform a device is running. */
export type PushPlatform = "android" | "ios";

/**
 * The data a notification carries, as the backend sends it.
 *
 * These keys are the server's own (``app/services/push.py``): ``event`` and
 * ``repository_number`` are what it writes into the payload. A notification
 * whose data did not match would still display, but tapping it would do
 * nothing, because there would be no repository to open.
 */
export interface NotificationData {
  /** The repository's UUID. */
  repository_id?: string;
  /** The repository's user-scoped number, which is what the app routes on. */
  repository_number?: number | string;
  /** The repository's display name. */
  repository_name?: string;
  /** What happened, e.g. ``ingest_complete``. */
  event?: string;
}

/**
 * Load `expo-notifications`.
 *
 * @returns The module.
 */
function notifications(): typeof import("expo-notifications") {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require("expo-notifications") as typeof import("expo-notifications");
}

/**
 * The platform this device is running.
 *
 * @returns The platform name the backend expects.
 */
export function currentPlatform(): PushPlatform {
  return Platform.OS === "ios" ? "ios" : "android";
}

/**
 * Whether the user has already allowed notifications.
 *
 * @returns True when notifications are allowed.
 */
export async function isPermissionGranted(): Promise<boolean> {
  try {
    const { status } = await notifications().getPermissionsAsync();
    return status === "granted";
  } catch {
    return false;
  }
}

/**
 * Ask the user for permission to send notifications.
 *
 * @returns True when the user allowed it.
 */
export async function requestPermission(): Promise<boolean> {
  try {
    const existing = await notifications().getPermissionsAsync();
    if (existing.status === "granted") return true;
    const asked = await notifications().requestPermissionsAsync();
    return asked.status === "granted";
  } catch {
    return false;
  }
}

/**
 * This device's Expo push token.
 *
 * @returns The token, or null when one could not be obtained.
 */
export async function getPushToken(): Promise<string | null> {
  try {
    const Constants = require("expo-constants").default as {
      easConfig?: { projectId?: string };
      expoConfig?: { extra?: { eas?: { projectId?: string } } };
    };
    const projectId =
      Constants.easConfig?.projectId ??
      Constants.expoConfig?.extra?.eas?.projectId;

    const token = await notifications().getExpoPushTokenAsync(
      projectId ? { projectId } : undefined,
    );
    return token?.data ?? null;
  } catch {
    return null;
  }
}

/**
 * Show notifications that arrive while the app is in the foreground.
 *
 * Without a handler, a foreground notification is silently dropped, which
 * makes the app look broken when the reader is looking right at it.
 */
export function setForegroundHandler(): void {
  try {
    notifications().setNotificationHandler({
      handleNotification: async () => ({
        shouldShowBanner: true,
        shouldShowList: true,
        shouldPlaySound: false,
        shouldSetBadge: false,
      }),
    });
  } catch {
    // A platform without notifications is not a failure.
  }
}

/**
 * Listen for the reader tapping a notification.
 *
 * @param handler - Called with the notification's data.
 * @returns A function that removes the listener.
 */
export function addResponseListener(
  handler: (data: NotificationData) => void,
): () => void {
  try {
    const subscription = notifications().addNotificationResponseReceivedListener(
      (response) => {
        handler((response.notification.request.content.data ?? {}) as NotificationData);
      },
    );
    return () => subscription.remove();
  } catch {
    return () => {};
  }
}

/**
 * The notification that opened the app, if one did.
 *
 * A cold start from a notification is the case where the tap happened
 * before there was anything to listen to, so the response is read from the
 * launch rather than from a tap.
 *
 * @returns The notification's data, or null.
 */
export async function getLaunchNotificationData(): Promise<NotificationData | null> {
  try {
    const response = await notifications().getLastNotificationResponseAsync();
    const data = response?.notification.request.content.data;
    return (data ?? null) as NotificationData | null;
  } catch {
    return null;
  }
}
