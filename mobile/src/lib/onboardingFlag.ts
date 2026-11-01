/**
 * The "the reader has already seen the onboarding carousel" flag.
 *
 * @module onboardingFlag
 *
 * The carousel is a one-time introduction, so the whole feature is a single
 * key in the app's key/value store:
 *
 * - :func:`hasSeenOnboarding` answers "should the carousel open?".
 * - :func:`markOnboardingSeen` records that it did.
 * - :func:`clearOnboardingSeen` puts the app back to a first run.
 *
 * The store is AsyncStorage rather than the secure store for one concrete
 * reason: AsyncStorage is wiped when the app is uninstalled, so a fresh
 * install shows the carousel again. A flag kept in the secure store would
 * survive the reinstall, and someone who reinstalls to start clean would
 * land on the login screen with no idea what the app does.
 *
 * Reads and writes are async because the underlying platform call is async;
 * render code must await the promise, never call these during render.
 *
 * The storage implementation is injectable so the unit tests can run in the
 * node environment without a native binding, exactly like
 * ``src/lib/tokenStore.ts`` does for the secure store.
 */

/** Single key used everywhere we persist the flag. */
export const ONBOARDING_SEEN_KEY = "illume:onboarding:seen";

/** The value stored under {@link ONBOARDING_SEEN_KEY}. */
const SEEN_VALUE = "1";

/**
 * The slice of the app's key/value store this module uses.
 *
 * Declared here rather than imported from the storage package so the module
 * carries no runtime dependency on a native binding.
 */
export interface OnboardingStorage {
  /** Read the value under a key; ``null`` when the key is absent. */
  getItem(key: string): Promise<string | null>;
  /** Write a value under a key, replacing any previous one. */
  setItem(key: string, value: string): Promise<void>;
  /** Remove a key. */
  removeItem(key: string): Promise<void>;
}

/**
 * The storage in use, or ``null`` when the default has not been loaded yet.
 */
let implementation: OnboardingStorage | null = null;

/**
 * Load the app's key/value store.
 *
 * The store is loaded on first use rather than at import time: the storage
 * package throws when it cannot find its native module, and there is no
 * native module in the node test environment. Importing it eagerly would
 * make this module unimportable outside the app -- and every route that
 * reads the flag imports this module.
 *
 * @returns The store's read, write and delete calls.
 */
function loadDefaultStorage(): OnboardingStorage {
  const loaded = require("@react-native-async-storage/async-storage") as {
    default?: OnboardingStorage;
  };
  const store = loaded.default ?? (loaded as unknown as OnboardingStorage);
  return {
    getItem: (key) => store.getItem(key),
    setItem: (key, value) => store.setItem(key, value),
    removeItem: (key) => store.removeItem(key),
  };
}

/**
 * The storage to talk to right now.
 *
 * @returns The injected storage, or the app's key/value store.
 */
function storage(): OnboardingStorage {
  if (!implementation) implementation = loadDefaultStorage();
  return implementation;
}

/**
 * Override the underlying storage. Used by tests to install an in-memory
 * implementation; never call this from production code.
 *
 * @param next - The storage calls this module should make from now on.
 */
export function __setOnboardingFlagImplementation(
  next: OnboardingStorage,
): void {
  implementation = next;
}

/**
 * Whether the reader has already been through the onboarding carousel.
 *
 * A read that fails is reported as "not seen". The carousel is harmless and
 * explains itself, so a broken read should never be the reason a first run
 * never sees it.
 *
 * @returns True when the carousel has been shown and finished.
 */
export async function hasSeenOnboarding(): Promise<boolean> {
  try {
    const value = await storage().getItem(ONBOARDING_SEEN_KEY);
    return value === SEEN_VALUE;
  } catch {
    return false;
  }
}

/**
 * Record that the reader has been through the onboarding carousel.
 *
 * Best-effort: a failed write is not fatal. The reader still gets to the
 * app, and the carousel simply opens again on the next cold start.
 */
export async function markOnboardingSeen(): Promise<void> {
  try {
    await storage().setItem(ONBOARDING_SEEN_KEY, SEEN_VALUE);
  } catch {
    // Nothing to do -- the flag stays unset and the carousel reopens.
  }
}

/**
 * Forget that the reader has seen the onboarding carousel, so the next cold
 * start opens it again.
 *
 * Idempotent -- removing a key that is not there is a no-op rather than an
 * error.
 */
export async function clearOnboardingSeen(): Promise<void> {
  try {
    await storage().removeItem(ONBOARDING_SEEN_KEY);
  } catch {
    // Nothing to do -- the flag stays as it was.
  }
}
