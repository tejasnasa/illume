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
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";

import { parseAuthCallback } from "@/lib/authCallback";
import { setAccessToken } from "@/lib/tokenStore";

export default function AuthCallbackScreen() {
  const params = useLocalSearchParams() as Record<string, string | string[]>;
  const handled = useRef(false);

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
        await setAccessToken(token);
        router.replace("/dashboard");
      })();
    } else {
      router.replace("/login");
    }
  }, [params]);

  return (
    <View style={styles.container}>
      <ActivityIndicator size="large" color="#fafafa" />
      <Text style={styles.title}>Completing sign-in…</Text>
      <Text style={styles.body}>
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

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  title: {
    color: "#fafafa",
    fontSize: 18,
    fontWeight: "600",
    marginTop: 16,
  },
  body: {
    color: "#9f9fa9",
    fontSize: 13,
    marginTop: 8,
    textAlign: "center",
  },
});
