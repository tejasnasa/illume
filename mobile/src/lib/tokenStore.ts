/**
 * Encrypted storage for the bearer token returned by the auth flow.
 *
 * Reads and writes are async because the underlying platform call is async;
 * render code must wait on the promise, never call these during render.
 */

import * as SecureStore from "expo-secure-store";

/** Single key used everywhere we persist the token. */
const TOKEN_KEY = "access_token";

/**
 * Test-only escape hatch. The default implementation calls
 * ``expo-secure-store``; in unit tests we substitute an in-memory shim so the
 * suite runs without a native binding.
 */
let implementation: Pick<typeof SecureStore, "getItemAsync" | "setItemAsync" | "deleteItemAsync"> = {
  getItemAsync: SecureStore.getItemAsync,
  setItemAsync: SecureStore.setItemAsync,
  deleteItemAsync: SecureStore.deleteItemAsync,
};

/**
 * Override the underlying storage. Used by tests to install an
 * in-memory implementation; never call this from production code.
 */
export function __setTokenStoreImplementation(
  next: Pick<typeof SecureStore, "getItemAsync" | "setItemAsync" | "deleteItemAsync">,
): void {
  implementation = next;
}

/**
 * Read the persisted access token.
 *
 * Returns ``null`` when no token is stored or the underlying store cannot be
 * read -- callers treat both cases as "logged out".
 */
export async function getAccessToken(): Promise<string | null> {
  try {
    return await implementation.getItemAsync(TOKEN_KEY);
  } catch {
    return null;
  }
}

/**
 * Persist the access token returned by the auth flow.
 *
 * Replaces any previous value. A failed write leaves the previous token
 * untouched (the store is atomic on the platforms we care about).
 */
export async function setAccessToken(token: string): Promise<void> {
  await implementation.setItemAsync(TOKEN_KEY, token);
}

/**
 * Remove the persisted token. Idempotent -- deleting when no value is set is
 * a no-op rather than an error.
 */
export async function clearAccessToken(): Promise<void> {
  await implementation.deleteItemAsync(TOKEN_KEY);
}
