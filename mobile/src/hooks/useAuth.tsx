/**
 * Authentication state for the app shell.
 *
 * The provider is mounted at the root; screens read ``token`` from the
 * context. Cold start is an effect: we read the token from the secure store,
 * hit ``/auth/me`` to validate it, and resolve to ``{ status: 'ready', token }``
 * or ``{ status: 'ready', token: null }`. Until that finishes we report
 * ``status: 'loading'`` so the route guards can show a splash rather than
 * bounce through ``/login`` and back.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AppState } from "react-native";

import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from "@/lib/tokenStore";
import { clearQueryCache } from "@/lib/queryClientRegistry";
import { resolveBackendUrl, setUnauthorizedHandler } from "@/api/client";
import { deregisterPushToken } from "@/api/push";
import { getPushToken } from "@/lib/pushNotifications";
import type User from "@/types/user";

/**
 * The profile returned by ``/auth/me``.
 *
 * Typed as the full :class:`User` record rather than a narrow subset:
 * the endpoint already sends the free-tier counters and the BYOK flag, so
 * narrowing them away here would only mean a second screen had to ask
 * for the same payload again. The raw API key is never returned -- the
 * server sends ``has_ai_key`` instead.
 */
type AuthUser = User;

interface AuthContextValue {
  /** While ``true`` the token store has not yet been read; guards must show a splash. */
  loading: boolean;
  /** Persisted bearer token, or ``null`` when no token (or validation failed). */
  token: string | null;
  /** Profile returned by ``/auth/me`` after a successful validation. */
  user: AuthUser | null;
  /**
   * Persist the token and validate it against the backend. Stores first,
   * validates second: a failure to validate simply leaves the user logged
   * out, but a token is never returned to the caller without being saved.
   *
   * @returns ``false`` when the backend rejected the token (the caller
   *   should route back to the login screen), ``true`` otherwise -- a
   *   network failure still counts as signed in, because the token may be
   *   perfectly valid and the profile is retried later.
   */
  signIn: (token: string) => Promise<boolean>;
  /** Drop the token and reset the in-memory profile. */
  signOut: () => Promise<void>;
  /**
   * Re-read the profile from ``/auth/me``.
   *
   * The free-tier counters change when a repository is created, so the
   * dashboard's banner would otherwise show a stale allowance until the
   * next cold start. A failed refresh leaves the current profile in
   * place -- a transient network error should not blank the banner.
   */
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

interface AuthProviderProps {
  children: ReactNode;
  /** Override for tests; defaults to ``fetch``. */
  fetchImpl?: typeof fetch;
  /** Backend base URL; reads ``EXPO_PUBLIC_BACKEND_URL`` at mount time. */
  backendUrl?: string;
}

/**
 * The outcome of validating a token against ``/auth/me``.
 *
 * ``unreachable`` is the important case: a network failure must not be
 * mistaken for an invalid session. On a phone the backend is a LAN address
 * that drops whenever the device changes network, and signing the reader out
 * because their train went into a tunnel is the wrong answer. Only a
 * ``rejected`` verdict -- a 401/403 -- means the token is actually dead.
 */
type MeResult =
  | { status: "ok"; user: AuthUser }
  | { status: "rejected" }
  | { status: "unreachable" };

/**
 * Read the current user from the backend using a bearer token.
 *
 * A non-401/403 failure (5xx, DNS, timeout, abort) resolves to
 * ``unreachable`` so the caller can keep a token that may still be valid.
 */
async function fetchMe(
  token: string,
  backendUrl: string,
  fetchImpl: typeof fetch,
): Promise<MeResult> {
  try {
    const response = await fetchImpl(`${backendUrl}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (response.status === 401 || response.status === 403) {
      return { status: "rejected" };
    }
    if (!response.ok) return { status: "unreachable" };
    return { status: "ok", user: (await response.json()) as AuthUser };
  } catch {
    return { status: "unreachable" };
  }
}

/**
 * Provide authentication state to the component tree.
 *
 * The provider does the cold-start read on mount; screens consume the
 * resolved state via :func:`useAuth`. The provider is intentionally dumb
 * about routing -- the ``(app)/_layout.tsx`` guard owns the redirect
 * decision, so this stays testable in isolation.
 */
export function AuthProvider({
  children,
  fetchImpl = fetch,
  backendUrl,
}: AuthProviderProps) {
  const [loading, setLoading] = useState(true);
  const [token, setTokenState] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);

  const baseUrl = useMemo(() => resolveBackendUrl(backendUrl), [backendUrl]);

  // The token whose profile fetch has already been retried, so a backend that
  // stays unreachable does not trigger a request per render.
  const retriedFor = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const stored = await getAccessToken();
      if (cancelled) return;
      if (!stored) {
        setLoading(false);
        return;
      }
      const me = await fetchMe(stored, baseUrl, fetchImpl);
      if (cancelled) return;
      if (me.status === "ok") {
        setTokenState(stored);
        setUser(me.user);
      } else if (me.status === "rejected") {
        // Token did not validate; drop it so the guard sends the user to
        // /login. Re-read first: a deep-link callback can write a fresh token
        // while this validation was in flight, and deleting that one would
        // be exactly the sign-in it was meant to complete.
        const current = await getAccessToken();
        if (current === stored) await clearAccessToken();
      } else {
        // The backend is unreachable. Keep the stored session -- the token may
        // still be valid -- and let the retry below fill in the profile.
        setTokenState(stored);
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [baseUrl, fetchImpl]);

  // A session that could not be validated on cold start (or that was signed
  // in while the backend was unreachable) has a token but no profile. Try
  // once more as soon as that changes; a 401 clears the session, a network
  // failure is left for the next focus event.
  useEffect(() => {
    if (!token || user) return;
    if (retriedFor.current === token) return;
    retriedFor.current = token;

    let cancelled = false;
    void (async () => {
      const me = await fetchMe(token, baseUrl, fetchImpl);
      if (cancelled) return;
      if (me.status === "ok") {
        setUser(me.user);
      } else if (me.status === "rejected") {
        await clearAccessToken();
        setTokenState(null);
        setUser(null);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token, user, baseUrl, fetchImpl]);

  // A profile that could not be read at launch is retried when the app
  // comes back to the foreground -- the case where the backend was
  // unreachable on launch and the network has since returned.
  useEffect(() => {
    if (!token) return;
    const subscription = AppState.addEventListener("change", (next) => {
      if (next !== "active" || user) return;
      void (async () => {
        const me = await fetchMe(token, baseUrl, fetchImpl);
        if (me.status === "ok") {
          setUser(me.user);
        } else if (me.status === "rejected") {
          await clearAccessToken();
          setTokenState(null);
          setUser(null);
        }
      })();
    });
    return () => subscription.remove();
  }, [token, user, baseUrl, fetchImpl]);

  const signIn = useCallback(
    async (next: string) => {
      await setAccessToken(next);
      const me = await fetchMe(next, baseUrl, fetchImpl);
      if (me.status === "ok") {
        setTokenState(next);
        setUser(me.user);
        return true;
      }
      if (me.status === "rejected") {
        // We persisted a token we cannot use. Clear it so the guard does not
        // bounce us back into the app on the next render.
        await clearAccessToken();
        setTokenState(null);
        setUser(null);
        return false;
      }
      // Signed in but the profile could not be read yet. Keep the session --
      // the retry effect above fills the profile in when the backend answers.
      setTokenState(next);
      return true;
    },
    [baseUrl, fetchImpl],
  );

  const signingOut = useRef(false);

  const signOut = useCallback(async () => {
    // The API client's 401 handler points here, and the deregistration call
    // below can itself come back 401 -- without this guard that is a loop.
    if (signingOut.current) return;
    signingOut.current = true;
    try {
      // The device stops receiving notifications about this account before
      // the token is dropped, so a signed-out phone is not left holding a
      // registration that still works.
      try {
        const pushToken = await getPushToken();
        if (pushToken) await deregisterPushToken(pushToken);
      } catch {
        // A push token that cannot be removed is not a reason to fail a
        // sign-out.
      }
      await clearAccessToken();
      setTokenState(null);
      setUser(null);
      // The cache holds the previous account's repositories, guide, graph
      // and chat. Clearing it is what stops a second sign-in in the same
      // process from reading the first account's data.
      clearQueryCache();
    } finally {
      signingOut.current = false;
    }
  }, []);

  // An expired session is a 401 on any request. Nothing else in the app can
  // reach the token state, so the client hands the event here.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      void signOut();
    });
    return () => setUnauthorizedHandler(null);
  }, [signOut]);

  const refreshUser = useCallback(async () => {
    if (!token) return;
    const me = await fetchMe(token, baseUrl, fetchImpl);
    if (me.status === "ok") setUser(me.user);
  }, [token, baseUrl, fetchImpl]);

  const value = useMemo<AuthContextValue>(
    () => ({ loading, token, user, signIn, signOut, refreshUser }),
    [loading, token, user, signIn, signOut, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * Read the auth context. Throws when called outside of an :class:`AuthProvider`
 * -- that is a programming error, not a runtime one, so we surface it loudly.
 */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
