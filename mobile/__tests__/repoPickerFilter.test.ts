/**
 * Tests for the repository picker's filtering behaviour.
 *
 * The filter is the one piece of picker logic that is not about React:
 * a name substring, case-insensitive, matching what the backend's own
 * filter means. Pinning it here keeps the search box honest and keeps
 * the semantics identical to the proxy's server-side filter.
 */

import { filterReposByName } from "@/hooks/useGitHubRepos";
import type { GitHubRepo } from "@/types/github";

/** Build a repository stub with the given name. */
function makeRepo(name: string): GitHubRepo {
  return {
    full_name: `owner/${name}`,
    name,
    private: false,
    default_branch: "main",
    description: null,
    language: null,
    updated_at: "2026-01-15T12:00:00Z",
    html_url: `https://github.com/owner/${name}`,
    stargazers_count: 0,
  };
}

const REPOS = [
  makeRepo("illume"),
  makeRepo("Illume-Spike"),
  makeRepo("other-project"),
];

describe("filterReposByName", () => {
  it("returns everything for an empty query", () => {
    expect(filterReposByName(REPOS, "")).toHaveLength(3);
  });

  it("matches a case-insensitive substring", () => {
    const result = filterReposByName(REPOS, "illume");
    expect(result.map((repo) => repo.name)).toEqual([
      "illume",
      "Illume-Spike",
    ]);
  });

  it("ignores surrounding whitespace", () => {
    const result = filterReposByName(REPOS, "  other  ");
    expect(result.map((repo) => repo.name)).toEqual(["other-project"]);
  });

  it("returns nothing when no name matches", () => {
    expect(filterReposByName(REPOS, "nonexistent")).toHaveLength(0);
  });
});
