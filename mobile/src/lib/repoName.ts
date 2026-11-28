/**
 * Owner and name parsing for repository labels.
 *
 * @module repoName
 *
 * Port of ``client/src/utils/repoName.ts``.
 */

/**
 * Split a GitHub URL into the owner prefix and repository name shown in
 * the repository bar and on dashboard cards.
 *
 * @param githubUrl - The repository's GitHub URL.
 * @param fallback - The stored repository name, used when the URL does not
 *   parse.
 * @returns The owner (possibly empty) and the name.
 */
export function splitRepoName(
  githubUrl: string | undefined,
  fallback: string,
): { owner: string; name: string } {
  const match = githubUrl?.match(/github\.com\/([^/]+)\/([^/#?]+)/i);
  if (!match) return { owner: "", name: fallback };
  return { owner: match[1], name: match[2].replace(/\.git$/i, "") };
}
