/**
 * A flat graph of the repository that lights the files a run touched.
 *
 * @module RunGraph
 *
 * Port of ``client/src/components/chat/LiveGraph.tsx`` for a phone. The web
 * draws a full-viewport 3D graph behind the conversation and runs a particle
 * along each edge the agent followed. Here the graph is a still react-native-
 * svg sketch under the activity of a turn, collapsed until the reader opens
 * it, so a long run costs nothing while it streams. A finished turn restored
 * from the server shows the files its answer cites; a run in this session
 * also shows every file it touched.
 */

import { useMemo, useState } from "react";
import { Pressable, Text, View } from "react-native";
import Svg, { Line, Rect } from "react-native-svg";

import type { Highlight, RunState } from "@/lib/agent/reducer";
import { SKETCH_H, SKETCH_W, sketchGraph } from "@/lib/overview";
import { IDLE_DOT, hasLitFiles, laneColorsOf, litPaths, looksFor } from "@/lib/runGraph";
import type Graph from "@/types/graph";

/** The squares of an idle file and a lit one. */
const BASE_SIZE = 3;

/**
 * Renders the panel.
 *
 * @param props - The file graph and the run to light it for.
 * @returns The panel, or nothing when the run lit no files.
 */
export function RunGraph({ graph, run }: { graph: Graph; run: RunState }) {
  const [open, setOpen] = useState(false);
  const highlight: Highlight = run.highlight;
  const live = run.status === "connecting" || run.status === "live";
  const lit = hasLitFiles(highlight);

  const touchedKey = lit ? highlight.touched.join("\n") + "|" + highlight.cited.join("\n") : "";
  const scene = useMemo(
    () => (open && lit ? sketchGraph(graph, litPaths(highlight)) : null),
    // The layout depends on which files are lit, not on every highlight change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [open, lit, graph, touchedKey],
  );
  const looks = useMemo(
    () => looksFor(highlight, laneColorsOf(run), live),
    [highlight, run, live],
  );

  if (!lit) return null;
  const count = new Set([...highlight.touched, ...highlight.cited]).size;

  return (
    <View testID="run-graph" className="overflow-hidden rounded-sm border border-border bg-card">
      <Pressable
        testID="run-graph-toggle"
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        accessibilityLabel={`Graph of ${count} files this answer used`}
        onPress={() => setOpen((v) => !v)}
        className="min-h-[40px] flex-row items-center justify-between px-3"
      >
        <Text className="font-pixel text-xs uppercase tracking-[0.7px] text-muted-foreground">
          Graph · {count} {count === 1 ? "file" : "files"}
        </Text>
        <Text className="font-pixel text-xs text-subtle-foreground">{open ? "−" : "+"}</Text>
      </Pressable>
      {open && scene ? (
        <View style={{ height: 170, backgroundColor: "#060608" }}>
          <Svg
            width="100%"
            height="100%"
            viewBox={`0 0 ${SKETCH_W} ${SKETCH_H}`}
            preserveAspectRatio="xMidYMid meet"
          >
            {scene.links.map(([a, b], i) => {
              const both = looks.has(a.path) && looks.has(b.path);
              return (
                <Line
                  key={i}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke={both ? "#7dd3fc" : "#94a3b8"}
                  strokeOpacity={both ? 0.6 : 0.07}
                  strokeWidth={1}
                />
              );
            })}
            {scene.points.map((p, i) => {
              const look = looks.get(p.path);
              const size = BASE_SIZE * (look?.scale ?? 1);
              return (
                <Rect
                  key={i}
                  x={Math.round(p.x - size / 2)}
                  y={Math.round(p.y - size / 2)}
                  width={size}
                  height={size}
                  fill={look?.color ?? IDLE_DOT}
                  fillOpacity={look ? look.opacity : 0.35}
                />
              );
            })}
          </Svg>
        </View>
      ) : null}
    </View>
  );
}
