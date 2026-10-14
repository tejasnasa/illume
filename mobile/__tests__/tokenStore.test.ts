/**
 * Round-trip tests for the encrypted storage adapter.
 *
 * The default implementation wraps ``expo-secure-store``, but we install an
 * in-memory shim here so the suite runs without binding native modules.
 */

import {
  __setTokenStoreImplementation,
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from "@/lib/tokenStore";

interface MemStore {
  getItemAsync(key: string): Promise<string | null>;
  setItemAsync(key: string, value: string): Promise<void>;
  deleteItemAsync(key: string): Promise<void>;
}

function makeMemStore(): MemStore & { data: Record<string, string> } {
  const data: Record<string, string> = {};
  return {
    data,
    async getItemAsync(key) {
      return key in data ? data[key] : null;
    },
    async setItemAsync(key, value) {
      data[key] = value;
    },
    async deleteItemAsync(key) {
      delete data[key];
    },
  };
}

describe("tokenStore", () => {
  let store: ReturnType<typeof makeMemStore>;

  beforeEach(() => {
    store = makeMemStore();
    __setTokenStoreImplementation(store);
  });

  it("returns null when nothing is stored", async () => {
    expect(await getAccessToken()).toBeNull();
  });

  it("returns the stored token after a write", async () => {
    await setAccessToken("jwt-abc");
    expect(await getAccessToken()).toBe("jwt-abc");
  });

  it("overwrites a previous token", async () => {
    await setAccessToken("first");
    await setAccessToken("second");
    expect(await getAccessToken()).toBe("second");
  });

  it("clears the token", async () => {
    await setAccessToken("to-be-cleared");
    await clearAccessToken();
    expect(await getAccessToken()).toBeNull();
  });

  it("clearing when empty is idempotent", async () => {
    await clearAccessToken();
    expect(await getAccessToken()).toBeNull();
  });

  it("returns null when the underlying store throws", async () => {
    __setTokenStoreImplementation({
      getItemAsync: () => Promise.reject(new Error("keystore unavailable")),
      setItemAsync: () => Promise.reject(new Error("keystore unavailable")),
      deleteItemAsync: () => Promise.reject(new Error("keystore unavailable")),
    });

    expect(await getAccessToken()).toBeNull();
  });
});
