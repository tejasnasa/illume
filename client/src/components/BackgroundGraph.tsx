/**
 * Non-interactive ambient pixel graph behind the repository pages.
 * @module BackgroundGraph
 */
"use client";
import PixelGraph from "@/components/PixelGraph";
import type Graph from "@/types/graph";

/**
 * Renders the repository's own constellation pinned behind the page.
 *
 * It drifts on its own and never follows the pointer, so it stays scenery
 * rather than competing with the page for attention.
 *
 * @param graph - Graph payload to draw; renders nothing when null.
 * @param veiled - Blurs and dims it until it is barely there, for pages
 *   where it should not compete with what sits on top.
 * @returns The background, or null while the graph is unavailable.
 */
export default function BackgroundGraph({
  graph,
  veiled = false,
}: {
  graph: Graph | null;
  veiled?: boolean;
}) {
  if (!graph || graph.nodes.length === 0) return null;
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 -z-10">
      <PixelGraph source={graph} focusLabel={false} />
      {veiled && (
        <div
          data-testid="background-veil"
          className="absolute inset-0 bg-(--background)/70 backdrop-blur-md"
        />
      )}
    </div>
  );
}
