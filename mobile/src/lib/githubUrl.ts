/**
 * GitHub repository URL parsing and validation.
 *
 * @module GitHubUrl
 *
 * The picker accepts a repository three ways: from the GitHub repo list
 * (where the owner and name come pre-split), from a pasted URL, and from
 * the branch/commit graph (which also needs owner and name to build the
 * proxy paths). All three converge on :func:`parseGitHubRepoUrl`, so the
 * one place that decides "is this a GitHub repository URL" is here.
 *
 * The pattern is the same one the web client uses in
 * ``client/src/components/RepoPickerModal.tsx``: an ``https://github.com``
 * origin, an owner segment, and a repository segment, with an optional
 * trailing slash. A trailing ``.git`` is tolerated and stripped from the
 * repository name, matching the web client's behaviour.
 */

/**
 * The owner/repository capture pattern.
 *
 * Exported so the error copy and the parser cannot drift apart.
 */
export const GITHUB_REPO_URL_PATTERN =
  /^https:\/\/github\.com\/([\w.-]+)\/([\w.-]+)\/?$/;

/** Owner and repository name extracted from a GitHub URL. */
export interface ParsedGitHubRepo {
  /** The user or organisation that owns the repository. */
  owner: string;
  /** The repository name, with any trailing ``.git`` removed. */
  name: string;
}

/**
 * Parse a GitHub repository URL into its owner and name.
 *
 * @param url - A candidate URL, typically pasted by the user.
 * @returns The owner and name, or ``null`` when the URL does not match.
 */
export function parseGitHubRepoUrl(url: string): ParsedGitHubRepo | null {
  const match = GITHUB_REPO_URL_PATTERN.exec(url.trim());
  if (!match) return null;
  return {
    owner: match[1],
    name: match[2].replace(/\.git$/, ""),
  };
}

/**
 * The copy shown when a pasted URL is not a GitHub repository URL.
 *
 * Kept next to the pattern so the message and the rule that rejects the
 * input live in the same file.
 */
export const INVALID_GITHUB_URL_MESSAGE =
  "Please enter a valid GitHub repository URL (e.g. https://github.com/user/repo)";

/**
 * The ``owner/name`` label for a repository.
 *
 * The web client splits the GitHub URL on ``github.com/``; the same split
 * is used here so a repository reads identically on both clients. The
 * stored name is the fallback for a URL that does not carry one.
 *
 * @param githubUrl - The repository's GitHub URL.
 * @param fallback - The repository's stored name.
 * @returns The label to display.
 */
export function formatRepoLabel(githubUrl: string, fallback: string): string {
  const parts = githubUrl.split("github.com/");
  return parts.length > 1 && parts[1] ? parts[1] : fallback;
}
