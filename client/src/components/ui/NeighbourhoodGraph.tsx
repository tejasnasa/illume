/**
 * A small pixel constellation of one file and the files it touches.
 * @module NeighbourhoodGraph
 */
"use client";

import PixelGraph, { type PixelDecoration } from "@/components/PixelGraph";
import type { PixelNode, PixelScene } from "@/lib/pixelGraph";
import type { FileNode } from "@/types/explorer";
import type Graph from "@/types/graph";
import { useCallback, useLayoutEffect, useMemo, useRef } from "react";

/** The selected file's colour: the accent pink, as a triple. */
const SELECTED_TINT = "246,51,154";

/**
 * Builds the graph of a file, its importers and its imports.
 *
 * @param file - The selected file.
 * @param importers - Files that import it.
 * @param imports - Files it imports.
 * @returns A graph holding each file once.
 */
export function neighbourhood(file: FileNode, importers: FileNode[], imports: FileNode[]): Graph {
  const nodes = new Map<string, FileNode>();
  for (const f of [file, ...importers, ...imports]) if (!nodes.has(f.id)) nodes.set(f.id, f);
  const links = [
    ...importers.map((f) => ({ source: f.id, target: file.id, type: "imports", weight: 1 })),
    ...imports.map((f) => ({ source: file.id, target: f.id, type: "imports", weight: 1 })),
  ];
  return {
    nodes: [...nodes.values()].map((f) => ({ ...f, criticality_score: 50 })),
    links,
    metadata: { total_nodes: nodes.size, total_edges: links.length, clusters: 0 },
  };
}

/**
 * Renders the neighbourhood, turned to face the selected file and naming it.
 *
 * @param file - The selected file.
 * @param importers - Files that import it.
 * @param imports - Files it imports.
 * @returns A canvas filling its positioned parent.
 */
export default function NeighbourhoodGraph({
  file,
  importers,
  imports,
}: {
  file: FileNode;
  importers: FileNode[];
  imports: FileNode[];
}) {
  // Keyed on the ids, so a parent handing over fresh but equal arrays does not
  // rebuild the scene and restart the animation.
  const key = [file.id, ...importers.map((f) => f.id), "|", ...imports.map((f) => f.id)].join(",");
  // eslint-disable-next-line react-hooks/exhaustive-deps -- the key covers all three
  const graph = useMemo(() => neighbourhood(file, importers, imports), [key]);
  const selected = useRef(file.path);
  useLayoutEffect(() => {
    selected.current = file.path;
  }, [file.path]);

  const decorate = useCallback((scene: PixelScene): PixelDecoration => {
    const path = selected.current;
    return {
      pinned: scene.byPath.get(path) ?? null,
      style: (n: PixelNode) =>
        n.kind === 0 && n.label === path ? { tint: SELECTED_TINT, glow: 1, scale: 1.6 } : null,
    };
  }, []);

  return (
    <PixelGraph
      source={graph}
      cell={3}
      focusLabel={false}
      turnTo={file.path}
      spreadY={0.42}
      lightRadius={0.34}
      decorate={decorate}
    />
  );
}
