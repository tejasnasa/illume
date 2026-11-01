/**
 * Tests for the onboarding carousel, the route that hosts it, and the entry
 * dispatcher that decides whether a cold start sees it at all.
 *
 * The carousel is easy to get wrong in three ways, and each has a test
 * here: it must show three screens and no more, it must be escapable from
 * the first one, and it must never get between a returning signed-in reader
 * and their dashboard.
 */

import React from "react";
import { Text } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { fireEvent, render, waitFor } from "@testing-library/react-native";

const mockRouterReplace = jest.fn();
const mockRouterBack = jest.fn();
let mockCanGoBack = false;

jest.mock("expo-router", () => ({
  __esModule: true,
  router: {
    replace: (...args: unknown[]) => mockRouterReplace(...args),
    back: (...args: unknown[]) => mockRouterBack(...args),
    canGoBack: () => mockCanGoBack,
  },
  useRouter: () => ({
    replace: (...args: unknown[]) => mockRouterReplace(...args),
    back: (...args: unknown[]) => mockRouterBack(...args),
    canGoBack: () => mockCanGoBack,
  }),
}));

import {
  OnboardingCarousel,
  ONBOARDING_PAGES,
} from "@/components/OnboardingCarousel";
import IndexRoute from "@/app/index";
import OnboardingRoute from "@/app/onboarding";
import { AuthProvider, useAuth } from "@/hooks/useAuth";
import { __setTokenStoreImplementation } from "@/lib/tokenStore";
import {
  __setOnboardingFlagImplementation,
  ONBOARDING_SEEN_KEY,
} from "@/lib/onboardingFlag";

interface MemStorage {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
  data: Record<string, string>;
  reads: number;
}

function makeMemStorage(initial: Record<string, string> = {}): MemStorage {
  const data: Record<string, string> = { ...initial };
  const storage: MemStorage = {
    data,
    reads: 0,
    async getItem(key) {
      storage.reads += 1;
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

function makeTokenStore(token: string | null) {
  return {
    async getItemAsync() {
      return token;
    },
    async setItemAsync() {},
    async deleteItemAsync() {},
  };
}

function makeFetch(user: object | null): typeof fetch {
  return (async () => ({
    ok: !!user,
    status: user ? 200 : 401,
    json: async () => user ?? {},
  })) as unknown as typeof fetch;
}

const SIGNED_IN_USER = { id: "u1", email: "a@b", name: "A", avatar_url: null };

/** The safe-area insets the carousel renders against. */
const SAFE_AREA_METRICS = {
  frame: { x: 0, y: 0, width: 0, height: 0 },
  insets: { top: 0, left: 0, right: 0, bottom: 0 },
};

/**
 * Render a tree inside the safe-area provider the app shell provides.
 *
 * @param ui - The tree to render.
 * @returns The rendered screen.
 */
async function renderWithSafeArea(ui: React.ReactElement) {
  const tree = (
    <SafeAreaProvider initialMetrics={SAFE_AREA_METRICS}>{ui}</SafeAreaProvider>
  );
  return await render(tree);
}

/** Reports the auth state, so a test can wait for the session to settle. */
function AuthProbe() {
  const { loading, token } = useAuth();
  return (
    <Text testID="auth-state">
      {loading ? "loading" : token ? "signed-in" : "signed-out"}
    </Text>
  );
}

describe("OnboardingCarousel", () => {
  beforeEach(() => {
    mockRouterReplace.mockClear();
    __setOnboardingFlagImplementation(makeMemStorage());
  });

  it("shows three screens", async () => {
    const screen = await renderWithSafeArea(<OnboardingCarousel />);

    expect(ONBOARDING_PAGES).toHaveLength(3);
    expect(screen.getByTestId("onboarding-page-0")).toBeTruthy();
    expect(screen.getByTestId("onboarding-page-1")).toBeTruthy();
    expect(screen.getByTestId("onboarding-page-2")).toBeTruthy();
  });

  it("explains what the app does, what it produces, and why it only reads", async () => {
    const screen = await renderWithSafeArea(<OnboardingCarousel />);

    expect(screen.getByText("It reads your repository")).toBeTruthy();
    expect(screen.getByText("It hands you a map")).toBeTruthy();
    expect(screen.getByText("It only ever reads")).toBeTruthy();
  });

  it("offers a way past the introduction on the first screen", async () => {
    const screen = await renderWithSafeArea(<OnboardingCarousel />);

    expect(screen.getByTestId("onboarding-skip")).toBeTruthy();
    expect(screen.queryByTestId("onboarding-get-started")).toBeNull();
  });

  it("marks the screen the reader is on", async () => {
    const screen = await renderWithSafeArea(<OnboardingCarousel />);

    expect(
      screen.getByTestId("onboarding-dot-0").props.accessibilityState.selected,
    ).toBe(true);

    await fireEvent.press(screen.getByTestId("onboarding-dot-2"));

    expect(
      screen.getByTestId("onboarding-dot-2").props.accessibilityState.selected,
    ).toBe(true);
    expect(
      screen.getByTestId("onboarding-dot-0").props.accessibilityState.selected,
    ).toBe(false);
  });

  it("offers the final button on the last screen", async () => {
    const screen = await renderWithSafeArea(<OnboardingCarousel />);

    await fireEvent.press(screen.getByTestId("onboarding-dot-2"));

    expect(screen.getByTestId("onboarding-get-started")).toBeTruthy();
  });
});

describe("OnboardingRoute", () => {
  let storage: MemStorage;

  beforeEach(() => {
    mockRouterReplace.mockClear();
    mockRouterBack.mockClear();
    storage = makeMemStorage();
    __setOnboardingFlagImplementation(storage);
    __setTokenStoreImplementation(makeTokenStore(null));
  });

  it("sends a skipping reader to the login screen", async () => {
    const screen = await renderWithSafeArea(
      <AuthProvider fetchImpl={makeFetch(null)}>
        <AuthProbe />
        <OnboardingRoute />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("auth-state")).toHaveTextContent("signed-out");
    });

    await fireEvent.press(screen.getByTestId("onboarding-skip"));

    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalledWith("/login");
    });
  });

  it("sends a finishing reader to the login screen and records the flag", async () => {
    const screen = await renderWithSafeArea(
      <AuthProvider fetchImpl={makeFetch(null)}>
        <AuthProbe />
        <OnboardingRoute />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("auth-state")).toHaveTextContent("signed-out");
    });

    await fireEvent.press(screen.getByTestId("onboarding-dot-2"));
    await fireEvent.press(screen.getByTestId("onboarding-get-started"));

    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalledWith("/login");
    });
    expect(storage.data[ONBOARDING_SEEN_KEY]).toBeDefined();
  });

  it("sends a reader who already has a session to the dashboard", async () => {
    __setTokenStoreImplementation(makeTokenStore("valid-jwt"));

    const screen = await renderWithSafeArea(
      <AuthProvider fetchImpl={makeFetch(SIGNED_IN_USER)}>
        <AuthProbe />
        <OnboardingRoute />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("auth-state")).toHaveTextContent("signed-in");
    });

    await fireEvent.press(screen.getByTestId("onboarding-skip"));

    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalledWith("/(app)/dashboard");
    });
  });

  it("pops back to the sign-in screen when reopened from it", async () => {
    // Reopened through the "?" on /login, the carousel sits on top of that
    // screen. Replacing would leave a second /login underneath, so the
    // exit is a pop.
    mockCanGoBack = true;

    try {
      const screen = await renderWithSafeArea(
        <AuthProvider fetchImpl={makeFetch(null)}>
          <AuthProbe />
          <OnboardingRoute />
        </AuthProvider>,
      );

      await waitFor(() => {
        expect(screen.getByTestId("auth-state")).toHaveTextContent(
          "signed-out",
        );
      });

      await fireEvent.press(screen.getByTestId("onboarding-skip"));

      await waitFor(() => {
        expect(mockRouterBack).toHaveBeenCalled();
      });
      expect(mockRouterReplace).not.toHaveBeenCalled();
      // Skipping counts as having seen it, whether it was pushed or not.
      expect(storage.data[ONBOARDING_SEEN_KEY]).toBeDefined();
    } finally {
      mockCanGoBack = false;
    }
  });
});

describe("IndexRoute", () => {
  let storage: MemStorage;

  beforeEach(() => {
    mockRouterReplace.mockClear();
    storage = makeMemStorage();
    __setOnboardingFlagImplementation(storage);
  });

  it("sends a signed-in reader straight to the dashboard", async () => {
    __setTokenStoreImplementation(makeTokenStore("valid-jwt"));

    const screen = await renderWithSafeArea(
      <AuthProvider fetchImpl={makeFetch(SIGNED_IN_USER)}>
        <AuthProbe />
        <IndexRoute />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalledWith("/(app)/dashboard");
    });
    expect(mockRouterReplace).not.toHaveBeenCalledWith("/onboarding");
    expect(screen.queryByTestId("onboarding-pages")).toBeNull();
  });

  it("does not make a signed-in reader wait on the flag", async () => {
    __setTokenStoreImplementation(makeTokenStore("valid-jwt"));

    await renderWithSafeArea(
      <AuthProvider fetchImpl={makeFetch(SIGNED_IN_USER)}>
        <IndexRoute />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalledWith("/(app)/dashboard");
    });
    expect(storage.reads).toBe(0);
  });

  it("sends a first-time reader to the carousel", async () => {
    __setTokenStoreImplementation(makeTokenStore(null));

    await renderWithSafeArea(
      <AuthProvider fetchImpl={makeFetch(null)}>
        <IndexRoute />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalledWith("/onboarding");
    });
    expect(mockRouterReplace).not.toHaveBeenCalledWith("/login");
  });

  it("sends a reader who has seen the carousel to the login screen", async () => {
    __setTokenStoreImplementation(makeTokenStore(null));
    __setOnboardingFlagImplementation(
      makeMemStorage({ [ONBOARDING_SEEN_KEY]: "1" }),
    );

    await renderWithSafeArea(
      <AuthProvider fetchImpl={makeFetch(null)}>
        <IndexRoute />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalledWith("/login");
    });
    expect(mockRouterReplace).not.toHaveBeenCalledWith("/onboarding");
  });
});
