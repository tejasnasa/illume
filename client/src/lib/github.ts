/**
 * GitHub deep-link helpers shared by the source-link cards.
 * @module github
 */

/** The last-resort ref for rows that record neither a commit nor a branch. */
export const FALLBACK_GITHUB_REF = "master";

/**
 * Picks the Git ref a GitHub blob link should point at.
 *
 * A link pinned to the ingested commit stays correct after the branch moves;
 * the answer was grounded in that snapshot, so the branch is only a fallback
 * for repositories ingested before the commit SHA was recorded. ``master`` is
 * the last resort for rows that carry neither.
 *
 * @param commitSha The commit the repository was ingested at, if recorded.
 * @param branch The branch the repository was ingested from, if recorded.
 * @returns The ref to place in the `/blob/<ref>/` segment.
 */
export function resolveGithubRef(
  commitSha?: string | null,
  branch?: string | null,
): string {
  if (commitSha && commitSha.length > 0) return commitSha;
  if (branch && branch.length > 0) return branch;
  return FALLBACK_GITHUB_REF;
}
