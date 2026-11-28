/**
 * The picture at the top of each repository card: a still frame of the
 * repository's own graph, condensed to its busiest files.
 *
 * @module RepoThumb
 *
 * Port of ``client/src/components/ui/RepoThumb.tsx``. A ready repository
 * fetches ``GET /repository/{id}/graph/thumbnail``; a card that is still
 * ingesting or failed, the moment before the graph arrives, and a graph that
 * could not be fetched or has no files all show a seeded placeholder
 * instead. A missing picture is never worth an error.
 */

import { useEffect, useMemo, useState } from "react";
import { View } from "react-native";
import Svg, { Line, Rect } from "react-native-svg";

import { apiGet } from "@/api/client";
import { layoutThumb, type ThumbSource } from "@/lib/thumbLayout";

/** Drawn width of the picture, in density-independent pixels. */
const WIDTH = 360;

/** Drawn height of the picture on a repository card. */
const DEFAULT_HEIGHT = 112;

/**
 * Renders the picture.
 *
 * @param props - The repository, whether to fetch its graph, and the
 *   height to draw at (the layout is fitted to it, not stretched).
 * @returns The picture.
 */
export function RepoThumb({
  repoId,
  tone = "ready",
  height = DEFAULT_HEIGHT,
}: {
  repoId: string;
  tone?: "ready" | "muted";
  height?: number;
}) {
  const [graph, setGraph] = useState<{ id: string; data: ThumbSource } | null>(null);

  useEffect(() => {
    if (tone !== "ready") return;
    const controller = new AbortController();
    apiGet<ThumbSource>(`/api/v1/repository/${repoId}/graph/thumbnail`, {
      signal: controller.signal,
    })
      .then((data) => {
        if (!controller.signal.aborted && data?.nodes?.length > 0) {
          setGraph({ id: repoId, data });
        }
      })
      .catch(() => {});
    return () => controller.abort();
  }, [repoId, tone]);

  const real = tone === "ready" && graph?.id === repoId ? graph.data : null;

  const scene = useMemo(() => {
    if (real) return layoutThumb(real, WIDTH, height, repoId);
    // The placeholder: a few seeded clusters in the same language.
    const nodes = Array.from({ length: 36 }, (_, i) => ({
      id: `p${i}`,
      group: `g${i % 5}`,
    }));
    const links = nodes.slice(1).map((node, i) => ({
      source: nodes[Math.floor(i / 2)].id,
      target: node.id,
    }));
    return layoutThumb({ nodes, links }, WIDTH, height, repoId);
  }, [real, repoId, height]);

  return (
    <View
      testID={real ? "repo-thumb-graph" : "repo-thumb-placeholder"}
      style={{ opacity: tone === "muted" ? 0.35 : 1, overflow: "hidden" }}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    >
      <Svg width="100%" height={height} viewBox={`0 0 ${WIDTH} ${height}`} preserveAspectRatio="xMidYMid slice">
        {scene.lines.map((line, i) => (
          <Line
            key={`l${i}`}
            x1={line.x1}
            y1={line.y1}
            x2={line.x2}
            y2={line.y2}
            stroke="#94a3b8"
            strokeOpacity={0.18}
            strokeWidth={1}
          />
        ))}
        {scene.pixels.map((pixel, i) => (
          <Rect
            key={`p${i}`}
            x={pixel.x}
            y={pixel.y}
            width={pixel.size}
            height={pixel.size}
            fill={pixel.color}
            opacity={pixel.hub ? 1 : 0.8}
          />
        ))}
      </Svg>
    </View>
  );
}
