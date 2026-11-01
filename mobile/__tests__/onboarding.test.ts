/**
 * Tests for the onboarding flag.
 *
 * The flag is the only thing that keeps the carousel to one showing per
 * install, so the cases that matter are the round trip, the clear, and the
 * two ways the underlying storage can misbehave. A read that fails must not
 * strand a first run on the login screen, and a write that fails must not
 * strand the reader on the carousel.
 */

import {
  __setOnboardingFlagImplementation,
  clearOnboardingSeen,
  hasSeenOnboarding,
  markOnboardingSeen,
  ONBOARDING_SEEN_KEY,
} from "@/lib/onboardingFlag";

interface MemStorage {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
  data: Record<string, string>;
  reads: string[];
}

function makeMemStorage(): MemStorage {
  const data: Record<string, string> = {};
  const storage: MemStorage = {
    data,
    reads: [],
    async getItem(key) {
      storage.reads.push(key);
      return key in data ? data[key] : null;
    },
    async setItem(key, value) {
      data[key] = value;
    },
    async removeItem(key) {
      delete data[key];
    },
  };
  return storage;
}

describe("onboardingFlag", () => {
  let storage: MemStorage;

  beforeEach(() => {
    storage = makeMemStorage();
    __setOnboardingFlagImplementation(storage);
  });

  it("reports the carousel as unseen before anything is written", async () => {
    expect(await hasSeenOnboarding()).toBe(false);
  });

  it("reports the carousel as seen once it has been marked", async () => {
    await markOnboardingSeen();
    expect(await hasSeenOnboarding()).toBe(true);
  });

  it("keeps the flag under a single known key", async () => {
    await markOnboardingSeen();

    expect(Object.keys(storage.data)).toEqual([ONBOARDING_SEEN_KEY]);
    expect(storage.reads).toEqual([]);
  });

  it("reads the flag back under that same key", async () => {
    await markOnboardingSeen();
    storage.reads.length = 0;

    await hasSeenOnboarding();

    expect(storage.reads).toEqual([ONBOARDING_SEEN_KEY]);
  });

  it("clears the flag so the carousel opens again", async () => {
    await markOnboardingSeen();
    await clearOnboardingSeen();

    expect(await hasSeenOnboarding()).toBe(false);
  });

  it("clearing when nothing is stored is idempotent", async () => {
    await clearOnboardingSeen();
    await clearOnboardingSeen();

    expect(await hasSeenOnboarding()).toBe(false);
  });

  it("treats a failed read as not seen", async () => {
    __setOnboardingFlagImplementation({
      getItem: () => Promise.reject(new Error("storage unavailable")),
      setItem: () => Promise.reject(new Error("storage unavailable")),
      removeItem: () => Promise.reject(new Error("storage unavailable")),
    });

    expect(await hasSeenOnboarding()).toBe(false);
  });

  it("survives a failed write", async () => {
    __setOnboardingFlagImplementation({
      getItem: () => Promise.reject(new Error("storage unavailable")),
      setItem: () => Promise.reject(new Error("storage unavailable")),
      removeItem: () => Promise.reject(new Error("storage unavailable")),
    });

    await expect(markOnboardingSeen()).resolves.toBeUndefined();
  });

  it("survives a failed clear", async () => {
    __setOnboardingFlagImplementation({
      getItem: () => Promise.reject(new Error("storage unavailable")),
      setItem: () => Promise.reject(new Error("storage unavailable")),
      removeItem: () => Promise.reject(new Error("storage unavailable")),
    });

    await expect(clearOnboardingSeen()).resolves.toBeUndefined();
  });
});
