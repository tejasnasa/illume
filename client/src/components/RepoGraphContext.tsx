/**
 * Shares the repository layout's graph payload with its client pages.
 * @module RepoGraphContext
 */
"use client";

import BackgroundGraph from "@/components/BackgroundGraph";
import type Graph from "@/types/graph";
import { usePathname } from "next/navigation";
import { createContext, useContext } from "react";

const RepoGraphContext = createContext<Graph | null>(null);

/** Matches the repository chat route, with or without a trailing slash. */
export function isChatPath(path: string | null): boolean {
  return Boolean(path && /\/repo\/[^/]+\/chat\/?$/.test(path));
}

/**
 * Provides the graph the layout already fetched.
 *
 * @param graph - File-level graph, or null when the repository is not ready.
 * @param children - The repository's pages.
 * @returns The provider.
 */
export function RepoGraphProvider({
  graph,
  children,
}: {
  graph: Graph | null;
  children: React.ReactNode;
}) {
  return (
    <RepoGraphContext.Provider value={graph}>
      {children}
    </RepoGraphContext.Provider>
  );
}

/** The graph the layout fetched, or null while the repository is indexing. */
export function useRepoGraph(): Graph | null {
  return useContext(RepoGraphContext);
}

/**
 * The ambient background for repository pages, skipped on the chat page.
 *
 * The chat page draws its own full-viewport graph that follows the agent, so
 * rendering this one as well would run two WebGL scenes on top of each other.
 *
 * @returns The ambient graph, or nothing on the chat route.
 */
export function AmbientBackground() {
  const graph = useRepoGraph();
  const path = usePathname();
  if (isChatPath(path)) return null;
  return <BackgroundGraph graph={graph} />;
}
