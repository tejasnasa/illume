/**
 * Deep-link target for the GitHub OAuth callback.
 *
 * The system browser redirects the user to ``illume://auth/callback?…`` after
 * the backend completes GitHub's exchange. This screen:
 *
 * 1. Reads the URL via ``useLocalSearchParams``.
 * 2. Extracts the token (or error) via :func:`parseAuthCallback`.
 * 3. Persists the token via :func:`setAccessToken` and pushes to the dashboard.
 * 4. Surfaces parse errors without crashing -- a missing or malformed token
 *    redirects to ``/login`` so the user can try again.
 *
 * Implementation note: do NOT route the params through ``URLSearchParams`` /
 * ``URL``. Android's ``URLSearchParams`` polyfill round-trips percent-encoding
 * inconsistently for the characters that show up in JWTs (``-``, ``_``, ``.``,
 * ``=``, and the inner slashes from base64-padding edge cases), which means
 * the parser can see a token but with one wrong character. The manual
 * percent-decoding in :func:`parseAuthCallback` is more reliable than the
 * global -- we feed it the raw joined query string with ``+`` as a literal
 * plus, exactly the shape the OS handed us.
 */

import { useEffect, useRef } from "react";
import { ActivityIndicator, Text, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";

import { parseAuthCallback } from "@/lib/authCallback";
import { useAuth } from "@/hooks/useAuth";
import { colors } from "@/theme/tokens";

export default function AuthCallbackScreen() {
  const params = useLocalSearchParams() as Record<string, string | string[]>;
  const handled = useRef(false);
  // ``signIn`` -- not a bare ``setAccessToken`` call -- because the route
  // guard reads the token from the auth context. Writing only the secure
  // store would leave that context at ``null`` and bounce the just-signed-in
  // reader straight back to the login screen.
  const { signIn } = useAuth();

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;

    // ``joinQuery`` rebuilds the raw query the OS delivered. We deliberately
    // skip ``URL`` and ``URLSearchParams`` here -- see the note in the file
    // header. ``+`` is left as a literal plus; tokens do not contain it.
    const rawQuery = joinQuery(params);
    const payload = parseAuthCallback(`illume://auth/callback?${rawQuery}`);
    const token = payload.token;

    if (token) {
      void (async () => {
        const accepted = await signIn(token);
        // A rejected token means the sign-in did not take; going on to the
        // dashboard would only be bounced back here by the guard, with the
        // reader given no reason why.
        router.replace(accepted ? "/dashboard" : "/login");
      })();
    } else {
      router.replace("/login");
    }
  }, [params, signIn]);

  return (
    <View className="flex-1 items-center justify-center bg-background p-6">
      <ActivityIndicator size="large" color={colors.foreground} />
      <Text className="mt-4 text-lg font-semibold text-foreground">
        Completing sign-in…
      </Text>
      <Text className="mt-2 text-center text-[13px] text-muted-foreground">
        You can close this screen if it does not advance.
      </Text>
    </View>
  );
}

/**
 * Concatenate the route params back into a query string the parser
 * understands.
 *
 * Each value is percent-encoded by hand because ``URLSearchParams`` is the
 * piece we are avoiding. The two characters that matter for a JWT are ``/``
 * (decoded) and ``.`` (decoded); base64-url uses ``-`` and ``_`` which are
 * already URL-safe.
 */
function joinQuery(params: Record<string, string | string[]>): string {
  const pairs: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    const values = Array.isArray(value) ? value : [value];
    for (const v of values) {
      pairs.push(`${encodeKey(key)}=${encodeValue(v)}`);
    }
  }
  return pairs.join("&");
}

function encodeKey(value: string): string {
  // Keys are simple ASCII from our backend, so this is just a defensive escape.
  return value.replace(/[^a-zA-Z0-9_-]/g, (char) => encodeURIComponent(char));
}

function encodeValue(value: string): string {
  // JWTs are base64-url -- letters, digits, ``-``, ``_``, and ``.``.
  // Pass those through, percent-encode anything else.
  return value.replace(/[^a-zA-Z0-9._-]/g, (char) => encodeURIComponent(char));
}
