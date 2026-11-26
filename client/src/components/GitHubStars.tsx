/**
 * Live star count for the navbar's GitHub button.
 * @module GitHubStars
 */
"use client";

import { useEffect, useState } from "react";

const CACHE_KEY = "illume:github-stars";
const CACHE_MS = 60 * 60 * 1000;

/**
 * Reads a cached count if it is still fresh.
 *
 * @param repo The `owner/name` the count belongs to.
 * @returns The cached count, or null.
 */
function readCache(repo: string): number | null {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { repo: string; at: number; n: number };
    if (parsed.repo !== repo || Date.now() - parsed.at > CACHE_MS) return null;
    return parsed.n;
  } catch {
    return null;
  }
}

/**
 * Fetches the repository's star count once per tab session and renders the
 * count half of the star button. Renders nothing until a count arrives, so a
 * rate-limited or offline visitor simply sees the GitHub mark on its own.
 *
 * @param repo The `owner/name` of the repository.
 * @returns The count segment, or nothing.
 */
export default function GitHubStars({ repo }: { repo: string }) {
  const [stars, setStars] = useState<number | null>(null);

  useEffect(() => {
    const cached = readCache(repo);
    if (cached !== null) {
      setStars(cached);
      return;
    }
    const controller = new AbortController();
    fetch(`https://api.github.com/repos/${repo}`, {
      headers: { Accept: "application/vnd.github+json" },
      signal: controller.signal,
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((body: { stargazers_count?: unknown } | null) => {
        const n = body?.stargazers_count;
        if (typeof n !== "number") return;
        setStars(n);
        try {
          sessionStorage.setItem(
            CACHE_KEY,
            JSON.stringify({ repo, at: Date.now(), n }),
          );
        } catch {
          // Storage can be unavailable (private mode); the count still shows.
        }
      })
      .catch(() => {});
    return () => controller.abort();
  }, [repo]);

  if (stars === null) return null;
  return (
    <span className="flex items-center gap-1.5 border-l border-(--border-strong) bg-white/3 px-3">
      <span aria-hidden="true" className="text-(--warning)">
        ★
      </span>
      {stars.toLocaleString("en-US")}
    </span>
  );
}
