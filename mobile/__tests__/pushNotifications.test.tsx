/**
 * Tests for push notification registration.
 *
 * Two things are worth pinning: the calls the app makes to the backend,
 * and the rule that the device re-registers itself on every launch --
 * Expo rotates push tokens, and a token the backend has never seen
 * delivers nothing.
 */

import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";

import {
  deregisterPushToken,
  getPushTokenStatus,
  registerPushToken,
} from "@/api/push";
import { AuthProvider } from "@/hooks/useAuth";
import {
  notificationPath,
  usePushNotifications,
} from "@/hooks/usePushNotifications";
import { __setTokenStoreImplementation } from "@/lib/tokenStore";

/** The state of the platform, as the test needs it to be. */
const platform = {
  permissionGranted: false,
  requestResult: true,
  token: "ExponentPushToken[abc]",
};

/** The calls the hook made to the backend. */
const calls: { method: string; path: string; body?: unknown }[] = [];

jest.mock("@/lib/pushNotifications", () => ({
  currentPlatform: () => "android",
  isPermissionGranted: async () => platform.permissionGranted,
  requestPermission: async () => {
    platform.permissionGranted = platform.requestResult;
    return platform.requestResult;
  },
  getPushToken: async () => platform.token,
  setForegroundHandler: () => {},
  addResponseListener: () => () => {},
  getLaunchNotificationData: async () => null,
}));

/**
 * The push calls among the recorded ones.
 *
 * The auth provider makes its own request on mount, so the recorded calls
 * have to be narrowed to the push endpoint before they mean anything.
 *
 * @returns The push calls.
 */
function pushCalls(): { method: string; path: string; body?: unknown }[] {
  return calls.filter((call) => call.path.includes("/push/"));
}

beforeEach(() => {
  calls.length = 0;
  platform.permissionGranted = false;
  platform.requestResult = true;
  platform.token = "ExponentPushToken[abc]";

  __setTokenStoreImplementation({
    async getItemAsync() {
      return "valid-jwt";
    },
    async setItemAsync() {},
    async deleteItemAsync() {},
  });
});

/**
 * Install a fetch stub that records what it was asked for.
 */
function stubFetch(): void {
  const fetchImpl = jest.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      calls.push({
        method: init?.method ?? "GET",
        path: url,
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      });
      return new Response(
        JSON.stringify({ registered: true, token_count: 1 }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    },
  );
  (global as unknown as { fetch: typeof fetch }).fetch =
    fetchImpl as unknown as typeof fetch;
}

describe("the push endpoints", () => {
  it("registers a token with its platform", async () => {
    stubFetch();
    await registerPushToken("token-1", "android", {
      backendUrl: "http://host",
    });

    expect(calls).toHaveLength(1);
    expect(calls[0].method).toBe("POST");
    expect(calls[0].path).toBe("http://host/api/v1/push/token");
    expect(calls[0].body).toEqual({ token: "token-1", platform: "android" });
  });

  it("removes a token", async () => {
    stubFetch();
    await deregisterPushToken("token-1", { backendUrl: "http://host" });

    expect(calls[0].method).toBe("DELETE");
    expect(calls[0].body).toEqual({ token: "token-1" });
  });

  it("asks whether the account has a device registered", async () => {
    stubFetch();
    const status = await getPushTokenStatus({ backendUrl: "http://host" });

    expect(calls[0].method).toBe("GET");
    expect(status.registered).toBe(true);
    expect(status.token_count).toBe(1);
  });
});

describe("the push hook", () => {
  it("registers the device when permission has already been given", async () => {
    platform.permissionGranted = true;
    stubFetch();

    const { result } = await renderHook(() => usePushNotifications(), {
      wrapper: ({ children }) => (
        <AuthProvider fetchImpl={fetch as unknown as typeof fetch}>
          {children}
        </AuthProvider>
      ),
    });

    await waitFor(() => expect(result.current.registered).toBe(true));
    expect(pushCalls()[0].body).toEqual({
      token: "ExponentPushToken[abc]",
      platform: "android",
    });
  });

  it("does not register a device that has not been allowed", async () => {
    stubFetch();

    const { result } = await renderHook(() => usePushNotifications(), {
      wrapper: ({ children }) => (
        <AuthProvider fetchImpl={fetch as unknown as typeof fetch}>
          {children}
        </AuthProvider>
      ),
    });

    await waitFor(() => expect(result.current.permissionGranted).toBe(false));
    expect(pushCalls()).toHaveLength(0);
  });

  it("asks for permission and registers when it is given", async () => {
    stubFetch();

    const { result } = await renderHook(() => usePushNotifications(), {
      wrapper: ({ children }) => (
        <AuthProvider fetchImpl={fetch as unknown as typeof fetch}>
          {children}
        </AuthProvider>
      ),
    });

    await act(async () => {
      await result.current.enable();
    });

    expect(result.current.permissionGranted).toBe(true);
    expect(result.current.registered).toBe(true);
  });

  it("registers nothing when the permission is refused", async () => {
    platform.requestResult = false;
    stubFetch();

    const { result } = await renderHook(() => usePushNotifications(), {
      wrapper: ({ children }) => (
        <AuthProvider fetchImpl={fetch as unknown as typeof fetch}>
          {children}
        </AuthProvider>
      ),
    });

    await act(async () => {
      await result.current.enable();
    });

    expect(result.current.registered).toBe(false);
    expect(pushCalls()).toHaveLength(0);
  });

  it("removes the device from the registry", async () => {
    stubFetch();

    const { result } = await renderHook(() => usePushNotifications(), {
      wrapper: ({ children }) => (
        <AuthProvider fetchImpl={fetch as unknown as typeof fetch}>
          {children}
        </AuthProvider>
      ),
    });

    await act(async () => {
      await result.current.disable();
    });

    expect(pushCalls().some((call) => call.method === "DELETE")).toBe(true);
  });
});

describe("a notification's link", () => {
  it("opens the repository it names", () => {
    expect(notificationPath({ repository_number: 42 })).toBe("/(app)/repo/42");
    expect(notificationPath({ repository_number: "42" })).toBe("/(app)/repo/42");
  });

  it("opens nothing when it names no repository", () => {
    expect(notificationPath(null)).toBeNull();
    expect(notificationPath({})).toBeNull();
    expect(notificationPath({ repository_number: "" })).toBeNull();
  });
});
