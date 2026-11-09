/**
 * Tracks a CSS media query on the client.
 * @module UseMediaQuery
 */
"use client";

import { useEffect, useState } from "react";

/**
 * Reports whether a media query currently matches.
 *
 * Starts as `false` on the server and on the first client render, so a heavy
 * component gated on a wide screen is never loaded for a phone: it mounts only
 * once the query is known to match.
 *
 * @param query - A media query such as `(min-width: 768px)`.
 * @returns Whether the query matches right now.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    update();
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, [query]);

  return matches;
}
