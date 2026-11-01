/**
 * Registering this device for push notifications.
 *
 * @module usePushNotifications
 *
 * The rules the product settled on:
 *
 * - **Permission is asked for after the first successful ingest**, not at
 *   launch. A cold permission prompt gets denied, because nobody knows
 *   what they are agreeing to yet.
 * - **The token is re-registered on every launch.** Expo push tokens
 *   rotate, and a token the backend has never seen is a token that
 *   delivers nothing.
 * - **Signing out removes the token.** A signed-out device has no business
 *   receiving notifications about somebody else's repositories.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "expo-router";

import {
  deregisterPushToken,
  registerPushToken,
} from "@/api/push";
import { useAuth } from "@/hooks/useAuth";
import {
  addResponseListener,
  currentPlatform,
  getLaunchNotificationData,
  getPushToken,
  isPermissionGranted,
  requestPermission,
  setForegroundHandler,
  type NotificationData,
} from "@/lib/pushNotifications";

/** What the hook exposes. */
export interface UsePushNotificationsResult {
  /** Whether the user has allowed notifications. */
  permissionGranted: boolean;
  /** Whether this device is registered with the backend. */
  registered: boolean;
  /**
   * Ask for permission and register the device.
   *
   * Safe to call more than once: a device that is already registered is
   * left alone.
   *
   * @returns True when the device ends up registered.
   */
  enable: () => Promise<boolean>;
  /** Remove this device from the backend's registry. */
  disable: () => Promise<void>;
}

/**
 * Register this device for push, and expose how to unregister it.
 *
 * @returns The registration state and the two actions.
 */
export function usePushNotifications(): UsePushNotificationsResult {
  const { token } = useAuth();
  const [permissionGranted, setPermissionGranted] = useState(false);
  const [registered, setRegistered] = useState(false);
  const inFlight = useRef(false);

  /**
   * Send this device's token to the backend.
   *
   * @returns True when the device is registered.
   */
  const register = useCallback(async (): Promise<boolean> => {
    if (!token) return false;
    const pushToken = await getPushToken();
    if (!pushToken) return false;
    try {
      const status = await registerPushToken(pushToken, currentPlatform());
      setRegistered(status.registered);
      return status.registered;
    } catch {
      return false;
    }
  }, [token]);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      const granted = await isPermissionGranted();
      if (cancelled) return;
      setPermissionGranted(granted);
      // A token the backend has never seen delivers nothing, and Expo
      // rotates tokens, so the device re-registers on every launch.
      if (granted) await register();
    })();

    return () => {
      cancelled = true;
    };
  }, [register]);

  const enable = useCallback(async (): Promise<boolean> => {
    if (inFlight.current) return registered;
    inFlight.current = true;
    try {
      const granted = await requestPermission();
      setPermissionGranted(granted);
      if (!granted) return false;
      return await register();
    } finally {
      inFlight.current = false;
    }
  }, [register, registered]);

  const disable = useCallback(async (): Promise<void> => {
    const pushToken = await getPushToken();
    if (!pushToken) return;
    try {
      await deregisterPushToken(pushToken);
    } catch {
      // A token the backend cannot find is already deregistered as far as
      // the reader is concerned.
    }
    setRegistered(false);
  }, []);

  return { permissionGranted, registered, enable, disable };
}

/**
 * Open the repository a notification is about.
 *
 * A notification is a link: tapping one lands on the repository it names.
 * The data carries the repository's user-scoped number, which is what the
 * app's routes are keyed on.
 *
 * @param data - The notification's data.
 * @returns The path to open, or null when the notification names no repository.
 */
export function notificationPath(data: NotificationData | null): string | null {
  if (!data) return null;
  // The server sends an empty string when the number is unknown, so an
  // empty value has to read the same as a missing one.
  const repoNumber = data.repository_number;
  if (repoNumber === undefined || repoNumber === null) return null;
  const asString = String(repoNumber).trim();
  if (!asString) return null;
  return `/(app)/repo/${asString}`;
}

/**
 * Route to the repository a tapped notification is about.
 *
 * The cold-start case is handled separately from the tap case: a
 * notification that launched the app was tapped before there was anything
 * listening.
 */
export function useNotificationNavigation(): void {
  const router = useRouter();

  useEffect(() => {
    setForegroundHandler();

    let cancelled = false;

    void (async () => {
      const data = await getLaunchNotificationData();
      if (cancelled) return;
      const path = notificationPath(data);
      if (path) router.push(path as never);
    })();

    const remove = addResponseListener((data) => {
      const path = notificationPath(data);
      if (path) router.push(path as never);
    });

    return () => {
      cancelled = true;
      remove();
    };
  }, [router]);
}
