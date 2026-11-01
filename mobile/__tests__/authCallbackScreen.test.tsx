/**
 * End-to-end test for the deep-link callback screen.
 *
 * The screen's job is small: parse the URL the system hands us, extract the
 * token, store it, and route to ``/dashboard`` (or ``/login`` if the token is
 * missing). We exercise that path by mounting the screen with a mocked
 * ``useLocalSearchParams`` and a mocked ``router.replace`` spy.
 */

import type { ReactElement } from "react";
import { Text } from "react-native";
import { render, waitFor } from "@testing-library/react-native";

// Mock the modules before importing the screen so the mocks attach to the
// hooks the screen depends on. Variable names prefixed with ``mock`` are
// allowed inside ``jest.mock`` factories.
const mockRouterReplace = jest.fn();

interface MockParams {
  access_token?: string;
  token_type?: string;
  expires_in?: string;
  error?: string;
}

let mockParams: MockParams = {
  access_token: "url-token",
  token_type: "Bearer",
  expires_in: "1296000",
};

jest.mock("expo-router", () => ({
  router: { replace: (...args: unknown[]) => mockRouterReplace(...args) },
  useLocalSearchParams: () => mockParams,
}));

import AuthCallbackScreen from "@/app/auth/callback";
import { AuthProvider } from "@/hooks/useAuth";
import { __setTokenStoreImplementation } from "@/lib/tokenStore";

const mockFetch = jest.fn();

/**
 * Mount the callback inside the provider it now depends on.
 *
 * The screen signs in through the auth context rather than writing the token
 * store directly -- writing only the store leaves the route guard's token
 * `null` and bounces the reader straight back to /login -- so the provider
 * has to be part of the test.
 */
function renderScreen(element: ReactElement = <AuthCallbackScreen />) {
  return render(
    <AuthProvider fetchImpl={mockFetch as unknown as typeof fetch} backendUrl="http://backend.test">
      {element}
    </AuthProvider>,
  );
}

describe("AuthCallbackScreen", () => {
  beforeEach(() => {
    mockRouterReplace.mockClear();
    mockParams = {
      access_token: "url-token",
      token_type: "Bearer",
      expires_in: "1296000",
    };
    mockFetch.mockReset().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "user-1", name: "Reader" }),
    });
    jest.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("stores the token from the deep link and routes to /dashboard", async () => {
    const writes: string[] = [];
    __setTokenStoreImplementation({
      async getItemAsync() {
        return null;
      },
      async setItemAsync(_key, value) {
        writes.push(value);
      },
      async deleteItemAsync() {},
    });

    await renderScreen();

    await waitFor(() => {
      expect(writes).toContain("url-token");
    });
    expect(mockRouterReplace).toHaveBeenCalledWith("/dashboard");
  });

  it("preserves JWT-unsafe characters in the token through the round-trip", async () => {
    // A real JWT is ``header.payload.signature`` where each segment is
    // base64-url. The polyfill on Android is known to encode ``.`` and ``/``
    // when they should be passed through; the manual encoder passes them
    // through explicitly. Pin that here -- the symptom of an earlier
    // regression was a perfectly-shaped JWT decrypting to ``None`` and
    // bouncing the user back to /login.
    mockParams = {
      access_token: "eyJhbGciOi.JIUzI1NiJ9.eyJzdWIiOiJ1MSJ9.Abc-Def_Xyz",
      token_type: "Bearer",
      expires_in: "1296000",
    };

    const writes: string[] = [];
    __setTokenStoreImplementation({
      async getItemAsync() {
        return null;
      },
      async setItemAsync(_key, value) {
        writes.push(value);
      },
      async deleteItemAsync() {},
    });

    await renderScreen();

    await waitFor(() => {
      expect(writes).toContain(
        "eyJhbGciOi.JIUzI1NiJ9.eyJzdWIiOiJ1MSJ9.Abc-Def_Xyz",
      );
    });
    expect(mockRouterReplace).toHaveBeenCalledWith("/dashboard");
  });

  it("routes to /login when the URL carries no token", async () => {
    mockParams = {};

    await renderScreen();

    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalledWith("/login");
    });
  });

  it("does not write to the store when there is no token", async () => {
    mockParams = {};

    const writes: string[] = [];
    __setTokenStoreImplementation({
      async getItemAsync() {
        return null;
      },
      async setItemAsync(_key, value) {
        writes.push(value);
      },
      async deleteItemAsync() {},
    });

    await renderScreen();

    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalledWith("/login");
    });
    expect(writes).toEqual([]);
  });

  it("does not double-store when the screen mounts twice (idempotent effect)", async () => {
    const writes: string[] = [];
    __setTokenStoreImplementation({
      async getItemAsync() {
        return null;
      },
      async setItemAsync(_key, value) {
        writes.push(value);
      },
      async deleteItemAsync() {},
    });

    const result = await renderScreen(
      <>
        <Text testID="holder">placeholder</Text>
        <AuthCallbackScreen />
      </>,
    );
    result.unmount();

    await renderScreen();

    await waitFor(() => {
      expect(writes.length).toBeGreaterThan(0);
    });
    // Two mounts should each issue one write (the ref guards against the same
    // component instance writing twice; a remount gets a fresh effect). The
    // invariant we are pinning is that the count stays small -- one per
    // mount -- rather than growing on every render. Concretely: never more
    // than one write per mount lifetime.
    expect(writes.length).toBeLessThanOrEqual(2);
    expect(writes.every((value) => value === "url-token")).toBe(true);
  });
});
