/**
 * Entry route.
 *
 * Hands off to the auth guard: ``(app)/dashboard`` when a token is held,
 * ``/login`` otherwise. The actual decision lives inside the guard so the
 * same logic runs on every navigation -- this file is just the dispatcher.
 */

import { Redirect } from "expo-router";

import { useAuth } from "@/hooks/useAuth";

export default function Index() {
  const { loading, token } = useAuth();

  if (loading) {
    // The root layout's splash would render before this; the redirect is
    // here so we resolve to the right place the moment loading flips.
    return null;
  }

  if (token) {
    return <Redirect href="/dashboard" />;
  }

  return <Redirect href="/login" />;
}
