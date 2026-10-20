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
      [...queryKeys.repositories.all, "glossary", id, page, query] as const,
    chatHistory: (id: string) =>
      [...queryKeys.repositories.all, "chat", id, "history"] as const,
  },

  /** GitHub proxy payloads (the user's repos, branches, commits). */
  github: {
    all: ["github"] as const,
    /**
     * The authenticated user's repository list.
     *
     * The picker filters client-side (see
     * :mod:`src.hooks.useGitHubRepos`), so this is a single cache entry
     * shared by every search term -- no refetch per keystroke, and no
     * cache entry per term either.
     */
    myRepos: () => [...queryKeys.github.all, "repos"] as const,
    branches: (owner: string, repo: string) =>
      [...queryKeys.github.all, "branches", owner, repo] as const,
    commits: (owner: string, repo: string, sha: string) =>
      [...queryKeys.github.all, "commits", owner, repo, sha] as const,
    /**
     * The merged multi-branch commit list the timeline renders.
     *
     * Separate from ``commits`` because the proxy exposes it at its own
     * path and returns a different shape (parents and branch names per
     * commit), so the two payloads must not share a cache entry.
     */
    multiBranchCommits: (owner: string, repo: string) =>
      [...queryKeys.github.all, "multiBranchCommits", owner, repo] as const,
  },
} as const;
