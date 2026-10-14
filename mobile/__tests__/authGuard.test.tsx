/**
 * Tests for the auth state machine.
 *
 * The guard's job is to translate auth state into a render: splash, login,
 * or the protected area. We exercise the path indirectly -- via the
 * :class:`AuthProvider` that the guard depends on -- because expo-router's
 * :component:`Redirect` needs the navigation container that production
 * ``RootLayout`` provides. Asserting on the provider's public surface
 * (loading flag, token, user) and on what the guard does with each state
 * keeps the test hermetic without poking at React Navigation internals.
 */

import { Text } from "react-native";
import { render, waitFor, act } from "@testing-library/react-native";

import { __setTokenStoreImplementation } from "@/lib/tokenStore";
import { AuthProvider, useAuth } from "@/hooks/useAuth";

interface MemStore {
  getItemAsync(key: string): Promise<string | null>;
  setItemAsync(key: string, value: string): Promise<void>;
  deleteItemAsync(key: string): Promise<void>;
  currentToken: string | null;
  writes: string[];
  deletes: number;
}

function makeMemStore(initial: string | null): MemStore {
  const store: MemStore = {
    currentToken: initial,
    writes: [],
    deletes: 0,
    async getItemAsync() {
      return store.currentToken;
    },
    async setItemAsync(_key, value) {
      store.writes.push(value);
      store.currentToken = value;
    },
    async deleteItemAsync() {
      store.deletes += 1;
      store.currentToken = null;
    },
  };
  return store;
}

function makeFetch(user: object | null, expectedUrl?: string): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    if (expectedUrl) {
      expect(String(input)).toBe(expectedUrl);
    }
    return {
      ok: !!user,
      status: user ? 200 : 401,
      json: async () => user ?? {},
    } as unknown as Response;
  }) as unknown as typeof fetch;
}

const ME_URL = "http://localhost:8000/api/v1/auth/me";

function Probe({ id = "probe" }: { id?: string }) {
  const { loading, token, user } = useAuth();
  return (
    <>
      <Text testID={`${id}-loading`}>{String(loading)}</Text>
      <Text testID={`${id}-token`}>{token ?? "null"}</Text>
      <Text testID={`${id}-user`}>{user ? user.email : "null"}</Text>
    </>
  );
}

describe("AuthProvider", () => {
  beforeEach(() => {
    jest.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("resolves to no token when the store is empty", async () => {
    __setTokenStoreImplementation(makeMemStore(null));

    const result = await render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(result.getByTestId("probe-loading").props.children).toBe("false");
      expect(result.getByTestId("probe-token").props.children).toBe("null");
    });
  });

  it("hydrates the token when the store returns one and the backend validates", async () => {
    __setTokenStoreImplementation(makeMemStore("valid-jwt"));

    const user = { id: "u1", email: "a@b", name: "A", avatar_url: null };
    const result = await render(
      <AuthProvider fetchImpl={makeFetch(user, ME_URL)}>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(result.getByTestId("probe-token").props.children).toBe(
        "valid-jwt",
      );
      expect(result.getByTestId("probe-user").props.children).toBe("a@b");
    });
  });

  it("clears the stored token when the backend rejects it", async () => {
    const store = makeMemStore("expired");
    __setTokenStoreImplementation(store);

    let callCount = 0;
    const fetchImpl: typeof fetch = (async () => {
      callCount += 1;
      return {
        ok: false,
        status: 401,
        json: async () => ({}),
      } as unknown as Response;
    }) as unknown as typeof fetch;

    const result = await render(
      <AuthProvider fetchImpl={fetchImpl}>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(result.getByTestId("probe-loading").props.children).toBe("false");
      expect(result.getByTestId("probe-token").props.children).toBe("null");
      expect(store.deletes).toBe(1);
      expect(callCount).toBe(1);
    });
  });

  it("treats a network failure as logged out and drops the token", async () => {
    const store = makeMemStore("stored-jwt");
    __setTokenStoreImplementation(store);

    const fetchImpl: typeof fetch = (async () => {
      throw new Error("network down");
    }) as unknown as typeof fetch;

    const result = await render(
      <AuthProvider fetchImpl={fetchImpl}>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(result.getByTestId("probe-token").props.children).toBe("null");
      expect(store.deletes).toBe(1);
    });
  });

  it("signIn stores the token and hydrates the user", async () => {
    const store = makeMemStore(null);
    __setTokenStoreImplementation(store);

    const user = { id: "u1", email: "a@b", name: "A", avatar_url: null };

    function Harness() {
      const { loading, token, user: u, signIn } = useAuth();
      return (
        <>
          <Text testID="loading">{String(loading)}</Text>
          <Text testID="token">{token ?? "null"}</Text>
          <Text testID="user">{u ? u.email : "null"}</Text>
          <Text testID="signin" onPress={() => void signIn("fresh-jwt")}>
            signin
          </Text>
        </>
      );
    }

    const result = await render(
      <AuthProvider fetchImpl={makeFetch(user)}>
        <Harness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(result.getByTestId("loading").props.children).toBe("false");
    });

    await act(async () => {
      result.getByTestId("signin").props.onPress();
    });

    await waitFor(() => {
      expect(result.getByTestId("token").props.children).toBe("fresh-jwt");
      expect(result.getByTestId("user").props.children).toBe("a@b");
      expect(store.writes).toContain("fresh-jwt");
    });
  });

  it("signIn clears the token when the backend rejects it on first use", async () => {
    const store = makeMemStore(null);
    __setTokenStoreImplementation(store);

    let calls = 0;
    const fetchImpl: typeof fetch = (async () => {
      calls += 1;
      return {
        ok: false,
        status: 401,
        json: async () => ({}),
      } as unknown as Response;
    }) as unknown as typeof fetch;

    function Harness() {
      const { token, signIn } = useAuth();
      return (
        <>
          <Text testID="token">{token ?? "null"}</Text>
          <Text testID="signin" onPress={() => void signIn("rejected-jwt")}>
            signin
          </Text>
        </>
      );
    }

    const result = await render(
      <AuthProvider fetchImpl={fetchImpl}>
        <Harness />
      </AuthProvider>,
    );

    await act(async () => {
      result.getByTestId("signin").props.onPress();
    });

    await waitFor(() => {
      expect(result.getByTestId("token").props.children).toBe("null");
      expect(calls).toBe(1);
      expect(store.writes).toContain("rejected-jwt");
      expect(store.deletes).toBe(1);
    });
  });

  it("signOut clears the token and the in-memory user", async () => {
    const store = makeMemStore("present");
    __setTokenStoreImplementation(store);

    const user = { id: "u1", email: "a@b", name: "A", avatar_url: null };

    function Harness() {
      const { token, user: u, signOut } = useAuth();
      return (
        <>
          <Text testID="token">{token ?? "null"}</Text>
          <Text testID="user">{u ? u.email : "null"}</Text>
          <Text testID="signout" onPress={() => void signOut()}>
            signout
          </Text>
        </>
      );
    }

    const result = await render(
      <AuthProvider fetchImpl={makeFetch(user)}>
        <Harness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(result.getByTestId("token").props.children).toBe("present");
    });

    await act(async () => {
      result.getByTestId("signout").props.onPress();
    });

    await waitFor(() => {
      expect(result.getByTestId("token").props.children).toBe("null");
      expect(result.getByTestId("user").props.children).toBe("null");
      expect(store.deletes).toBe(1);
    });
  });

  it("throws when useAuth is called outside of a provider", async () => {
    function NakedProbe() {
      useAuth();
      return <Text testID="probe">probe</Text>;
    }

    const spy = jest.spyOn(console, "error").mockImplementation(() => {});
    await expect(render(<NakedProbe />)).rejects.toThrow(/AuthProvider/);
    spy.mockRestore();
  });
});
