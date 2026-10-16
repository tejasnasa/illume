/**
 * Centralised TanStack Query key factory.
 *
 * Every cache key in the app is built by these helpers, so cache
 * invalidation in later phases has one place to look. The keys are
 * arrays of strings (the convention TanStack Query itself documents
 * for hierarchical invalidation); the leading element is the
 * "domain" so ``queryClient.invalidateQueries({ queryKey: keys.auth })``
 * flushes every auth-related cache entry in one call.
 *
 * Keeping the keys as data -- not as functions returning ``as const``
 * arrays -- would force callers to repeat the string literals. The
 * helper-per-domain shape lets later phases add granular keys (e.g.
 * ``keys.repository(id).guide``) without rewriting every callsite.
 */

export const queryKeys = {
  /** Authenticated profile returned by ``/auth/me``. */
  auth: {
    /** All auth-scoped keys. Use for a blanket sign-out flush. */
    all: ["auth"] as const,
    /** The current-user profile. */
    me: () => [...queryKeys.auth.all, "me"] as const,
  },

  /** Per-user repository list and per-repository detail payloads. */
  repositories: {
    all: ["repositories"] as const,
    list: () => [...queryKeys.repositories.all, "list"] as const,
    detail: (id: string) =>
      [...queryKeys.repositories.all, "detail", id] as const,
    graph: (id: string, level: "file" | "symbol") =>
      [...queryKeys.repositories.all, "graph", id, level] as const,
    guide: (id: string) =>
      [...queryKeys.repositories.all, "guide", id] as const,
    stats: (id: string) =>
      [...queryKeys.repositories.all, "stats", id] as const,
    explorer: (id: string) =>
      [...queryKeys.repositories.all, "explorer", id] as const,
    ownership: (id: string) =>
      [...queryKeys.repositories.all, "ownership", id] as const,
    glossary: (id: string, page: number, query: string) =>
      [
        ...queryKeys.repositories.all,
        "glossary",
        id,
        page,
        query,
      ] as const,
    chatHistory: (id: string) =>
      [...queryKeys.repositories.all, "chat", id, "history"] as const,
  },

  /** GitHub proxy payloads (the user's repos, branches, commits). */
  github: {
    all: ["github"] as const,
    myRepos: (query: string) =>
      [...queryKeys.github.all, "repos", query] as const,
    branches: (owner: string, repo: string) =>
      [...queryKeys.github.all, "branches", owner, repo] as const,
    commits: (owner: string, repo: string, sha: string) =>
      [...queryKeys.github.all, "commits", owner, repo, sha] as const,
  },
} as const;
