/**
 * The ingestion pipeline drawn as an animated flow graph.
 *
 * Every edge is authored geometry rather than a measured path, so the
 * travelling pulse is driven by literal numbers and nothing has to be
 * re-measured on resize.
 *
 * @module IngestFlowCanvas
 */

"use client";

import type { NodeState, StageStateMap } from "@/types/ingest";
import {
  EDGES,
  NODES,
  NODE_HEIGHT,
  NODE_WIDTH,
  VIEWBOX,
  normaliseTimes,
  pathFromPoints,
  type FlowEdge,
  type FlowNode,
} from "@/utils/ingestFlow";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { memo, useEffect, useRef, useState } from "react";

/** Stable identity for an edge, used to track which pulses are in flight. */
function edgeId(edge: FlowEdge): string {
  return `${edge.from}->${edge.to}`;
}

/** Stroke and weight for a node, chosen so the four states differ by shape. */
function nodeStroke(state: NodeState): {
  stroke: string;
  width: number;
  dash?: string;
} {
  switch (state) {
    case "done":
      return { stroke: "var(--success)", width: 1.5 };
    case "active":
      return { stroke: "var(--chart-1)", width: 1.5 };
    case "failed":
      return { stroke: "var(--destructive)", width: 2, dash: "5 4" };
    default:
      return { stroke: "var(--border)", width: 1, dash: "3 5" };
  }
}

/** The small marker inside each node. Glyphs, not just colour, carry the state. */
function StateGlyph({
  state,
  x,
  y,
}: {
  state: NodeState;
  x: number;
  y: number;
}) {
  if (state === "done") {
    return (
      <g>
        <circle cx={x} cy={y} r={7} fill="var(--success)" />
        <path
          d={`M ${x - 3.2} ${y} l 2.4 2.4 l 4.2 -4.6`}
          fill="none"
          stroke="var(--background)"
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
    );
  }

  if (state === "failed") {
    return (
      <g>
        <circle
          cx={x}
          cy={y}
          r={7}
          fill="none"
          stroke="var(--destructive)"
          strokeWidth={1.5}
        />
        <path
          d={`M ${x - 3} ${y - 3} l 6 6 M ${x + 3} ${y - 3} l -6 6`}
          stroke="var(--destructive)"
          strokeWidth={1.6}
          strokeLinecap="round"
        />
      </g>
    );
  }

  if (state === "active") {
    return (
      <circle
        className="flow-node-ring"
        cx={x}
        cy={y}
        r={7}
        fill="none"
        stroke="var(--chart-1)"
        strokeWidth={2}
        strokeDasharray="4 3"
        strokeLinecap="round"
      />
    );
  }

  return (
    <circle
      cx={x}
      cy={y}
      r={5}
      fill="none"
      stroke="var(--border)"
      strokeWidth={1.5}
    />
  );
}

/** One stage box. Memoised so a parse progress tick re-renders one text node. */
const FlowNodeBox = memo(function FlowNodeBox({
  node,
  state,
  progress,
}: {
  node: FlowNode;
  state: NodeState;
  progress?: { processed: number; total: number };
}) {
  const { stroke, width, dash } = nodeStroke(state);
  const x = node.cx - NODE_WIDTH / 2;
  const y = node.cy - NODE_HEIGHT / 2;
  const dimmed = state === "pending";

  return (
    <g>
      <rect
        x={x}
        y={y}
        width={NODE_WIDTH}
        height={NODE_HEIGHT}
        rx={6}
        fill="var(--card)"
        stroke={stroke}
        strokeWidth={width}
        strokeDasharray={dash}
      />
      <StateGlyph state={state} x={x + 22} y={node.cy} />
      <text
        x={x + 40}
        y={progress ? node.cy - 4 : node.cy + 4}
        fill={dimmed ? "var(--muted-foreground)" : "var(--foreground)"}
        fontSize={13}
        fontWeight={state === "active" ? 600 : 400}
      >
        {node.label}
      </text>
      {progress && (
        <text
          x={x + 40}
          y={node.cy + 12}
          fill="var(--muted-foreground)"
          fontSize={11}
        >
          {progress.processed.toLocaleString()}/
          {progress.total.toLocaleString()}
        </text>
      )}
    </g>
  );
});

/**
 * The flow graph.
 *
 * @param states - Current state of every stage.
 * @returns The animated pipeline canvas plus a screen-reader summary.
 */
export default function IngestFlowCanvas({
  states,
}: {
  states: StageStateMap;
}) {
  const reduced = useReducedMotion();
  const [pulses, setPulses] = useState<string[]>([]);
  const previous = useRef<StageStateMap>(states);
  const initialised = useRef(false);

  useEffect(() => {
    // The first pass is the seeded state, not a transition: replaying a pulse
    // for every already-finished stage would be a burst of noise on load.
    if (!initialised.current) {
      initialised.current = true;
      previous.current = states;
      return;
    }

    const newlyDone = EDGES.filter((edge) => {
      const was = previous.current[edge.from]?.state;
      const now = states[edge.from]?.state;
      return was !== "done" && now === "done";
    }).map(edgeId);

    previous.current = states;

    if (newlyDone.length > 0 && !reduced) {
      setPulses((current) => [...current, ...newlyDone]);
    }
  }, [states, reduced]);

  const stateOf = (id: string): NodeState => states[id]?.state ?? "pending";

  return (
    <div className="relative h-full w-full">
      <svg
        viewBox={`0 0 ${VIEWBOX.width} ${VIEWBOX.height}`}
        preserveAspectRatio="xMidYMid meet"
        className="h-full w-full"
        aria-hidden="true"
      >
        {/* Base edges: always present, so the graph reads before anything runs. */}
        <g>
          {EDGES.map((edge) => (
            <path
              key={`base-${edgeId(edge)}`}
              d={pathFromPoints(edge.points)}
              fill="none"
              stroke="var(--border)"
              strokeWidth={edge.kind === "sidecar" ? 1 : 1.5}
              strokeDasharray={edge.kind === "sidecar" ? "4 4" : undefined}
            />
          ))}
        </g>

        {/* Lit edges: drawn once, when their source stage completes. */}
        <g>
          {EDGES.map((edge) => {
            const lit = stateOf(edge.from) === "done";
            if (!lit) return null;
            return (
              <motion.path
                key={`lit-${edgeId(edge)}`}
                d={pathFromPoints(edge.points)}
                fill="none"
                stroke="var(--chart-1)"
                strokeWidth={edge.kind === "sidecar" ? 1.2 : 1.8}
                strokeDasharray={edge.kind === "sidecar" ? "4 4" : undefined}
                initial={reduced ? false : { pathLength: 0, opacity: 0.4 }}
                animate={{ pathLength: 1, opacity: 1 }}
                transition={{ duration: 0.55, ease: "easeOut" }}
              />
            );
          })}
        </g>

        {/* Pulses: one per newly-completed source, removed as each finishes so
            nothing is ever left looping. */}
        <AnimatePresence>
          {pulses.map((id) => {
            const edge = EDGES.find((candidate) => edgeId(candidate) === id);
            if (!edge) return null;
            const times = normaliseTimes(edge.points);
            return (
              <motion.circle
                key={`pulse-${id}`}
                r={4}
                fill="var(--chart-1)"
                initial={{
                  cx: edge.points[0][0],
                  cy: edge.points[0][1],
                  opacity: 0,
                }}
                animate={{
                  cx: edge.points.map((point) => point[0]),
                  cy: edge.points.map((point) => point[1]),
                  opacity: [0, 1, 1, 0],
                }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.7, ease: "easeInOut", times }}
                onAnimationComplete={() =>
                  setPulses((current) =>
                    current.filter((entry) => entry !== id),
                  )
                }
              />
            );
          })}
        </AnimatePresence>

        {/* Nodes. */}
        <g>
          {NODES.map((node) => (
            <FlowNodeBox
              key={node.id}
              node={node}
              state={stateOf(node.id)}
              progress={states[node.id]?.progress}
            />
          ))}
        </g>
      </svg>

      {/* The SVG is decorative; this is what a screen reader gets. Progress
          numbers are deliberately excluded -- a ten-thousand-file parse would
          otherwise announce hundreds of times over. */}
      <ol className="sr-only" aria-live="polite" aria-atomic="false">
        {NODES.map((node) => (
          <li key={node.id}>
            {node.label}: {stateOf(node.id)}
          </li>
        ))}
      </ol>
    </div>
  );
}
