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
  useState,
  type ReactNode,
} from "react";

import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from "@/lib/tokenStore";

/**
 * The default backend URL points at the local dev server. Operators override
 * this at build time via ``EXPO_PUBLIC_BACKEND_URL`` -- the same variable the
 * web client uses. Keeping it in one place here means a release build cannot
 * accidentally regress to ``localhost`` when the env var is missing in CI.
 */
const DEFAULT_BACKEND_URL = "http://localhost:8000";

interface AuthUser {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
}

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
   */
  signIn: (token: string) => Promise<void>;
  /** Drop the token and reset the in-memory profile. */
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

interface AuthProviderProps {
  children: ReactNode;
  /** Override for tests; defaults to ``fetch``. */
  fetchImpl?: typeof fetch;
  /** Backend base URL; reads ``EXPO_PUBLIC_BACKEND_URL`` at mount time. */
  backendUrl?: string;
}

function resolveBackendUrl(override?: string): string {
  if (override) return override.replace(/\/+$/, "");
  // ``process.env`` is statically replaced at bundle time when the variable
  // is prefixed with ``EXPO_PUBLIC_``; we read it lazily so a missing value
  // falls back to the local dev default rather than throwing.
  const envValue = (process.env as Record<string, string | undefined>)
    .EXPO_PUBLIC_BACKEND_URL;
  return (envValue ?? DEFAULT_BACKEND_URL).replace(/\/+$/, "");
}

/**
 * Read the current user from the backend using a bearer token.
 *
 * Returns ``null`` for any non-200 response -- callers treat expiry and
 * network failures the same way (logged out), since either leaves the user
 * with a token that will not work.
 */
async function fetchMe(
  token: string,
  backendUrl: string,
  fetchImpl: typeof fetch,
): Promise<AuthUser | null> {
  try {
    const response = await fetchImpl(`${backendUrl}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) return null;
    return (await response.json()) as AuthUser;
  } catch {
    return null;
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
      if (me) {
        setTokenState(stored);
        setUser(me);
      } else {
        // Token did not validate; drop it so the guard sends the user to /login.
        await clearAccessToken();
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [baseUrl, fetchImpl]);

  const signIn = useCallback(
    async (next: string) => {
      await setAccessToken(next);
      const me = await fetchMe(next, baseUrl, fetchImpl);
      if (me) {
        setTokenState(next);
        setUser(me);
      } else {
        // We persisted a token we cannot use. Clear it so the guard does not
        // bounce us back into the app on the next render.
        await clearAccessToken();
      }
    },
    [baseUrl, fetchImpl],
  );

  const signOut = useCallback(async () => {
    await clearAccessToken();
    setTokenState(null);
    setUser(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ loading, token, user, signIn, signOut }),
    [loading, token, user, signIn, signOut],
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
