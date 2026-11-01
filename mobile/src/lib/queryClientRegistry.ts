/**
 * A module-level handle on the app's query cache.
 *
 * The auth provider has to be able to clear the cache on sign-out, but it
 * also has to work outside a {@link QueryClientProvider} -- the auth specs
 * mount it on its own. Reading the client through a hook would throw there,
 * and threading a prop through every screen would make the provider's
 * contract depend on the router tree.
 *
 * So the root layout registers the client once, and the few non-React
 * callers reach it through here. Nothing is cached locally: the registry
 * holds the same instance the provider renders with.
 */

import type { QueryClient } from "@tanstack/react-query";

let registered: QueryClient | null = null;

/**
 * Record the app's query client.
 *
 * @param client - The client the root layout created.
 * @returns A function that unregisters it, for the layout's cleanup.
 */
export function registerQueryClient(client: QueryClient): () => void {
  registered = client;
  return () => {
    if (registered === client) registered = null;
  };
}

/**
 * Drop every cached query and mutation.
 *
 * Used on sign-out: the cache holds the previous account's repositories,
 * guides, graphs and chat, and the keys are not scoped by user.
 */
export function clearQueryCache(): void {
  registered?.clear();
}
