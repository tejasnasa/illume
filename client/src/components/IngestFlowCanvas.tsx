/**
 * The ingestion pipeline drawn as an animated flow graph.
 *
 * Every edge is authored geometry rather than a measured path, so the
 * travelling comet is driven by literal numbers and nothing has to be
 * re-measured on resize.
 *
 * All motion is either a one-shot animation that unmounts itself or a CSS
 * keyframe. There is deliberately no `requestAnimationFrame` loop: the graph
 * has to sit on screen for minutes at a time, and a per-frame JavaScript cost
 * would be paid for the whole of it.
 *
 * @module IngestFlowCanvas
 */

"use client";

import type { NodeState, StageStateMap } from "@/types/ingest";
import {
  EDGES,
  NODES,
  NODES_BY_ID,
  NODE_HEIGHT,
  NODE_WIDTH,
  VIEWBOX,
  isComplete,
  isFlowing,
  isLit,
  pathFromPoints,
  pathLengthOf,
  type FlowEdge,
  type FlowNode,
} from "@/utils/ingestFlow";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { memo, useEffect, useRef, useState } from "react";

/** Length of the travelling comet, in canvas units. */
const COMET_LENGTH = 30;

/** Stable identity for an edge. Hyphens, so it is safe inside a DOM id. */
function edgeId(edge: FlowEdge): string {
  return `${edge.from}--${edge.to}`;
}

/**
 * The single place a node state maps to a colour.
 *
 * Border, glyph and edge gradient all read from here; when they drifted apart
 * the same node could show two different "active" colours at once.
 */
function stateColor(state: NodeState): string {
  switch (state) {
    case "done":
      return "var(--success)";
    case "active":
      return "var(--primary)";
    case "failed":
      return "var(--destructive)";
    default:
      return "var(--border)";
  }
}

/**
 * A luminous form of the state colour, for halos and glows.
 *
 * `--primary` is dark (lightness 0.459), so used raw as a glow it reads as a
 * smudge rather than a light. Lifting the lightness keeps the brand hue while
 * making the working node the brightest thing on the canvas -- otherwise the
 * active stage would render dimmer than the finished ones.
 */
function glowColor(state: NodeState): string {
  switch (state) {
    case "active":
      return "oklch(from var(--primary) 0.78 c h)";
    default:
      return stateColor(state);
  }
}

/**
 * The colour a lit edge fades into at its far end.
 *
 * A barrier is not a stage, and a stage that has not started yet has no
 * colour of its own. Both used to resolve to `--border`, so the line appeared
 * to die partway along -- which reads as a rendering fault rather than as
 * anything about the pipeline. They fall back to the source colour instead.
 */
function edgeEndColor(edge: FlowEdge, states: StageStateMap): string {
  const target = states[edge.to]?.state;
  if (!target || target === "pending") return stateColor("done");
  return stateColor(target);
}

/** Stroke weight and dash pattern, chosen so the four states differ by shape. */
function nodeStroke(state: NodeState): {
  stroke: string;
  width: number;
  dash?: string;
} {
  switch (state) {
    case "done":
      return { stroke: stateColor(state), width: 1.5 };
    case "active":
      return { stroke: stateColor(state), width: 2 };
    case "failed":
      return { stroke: stateColor(state), width: 2, dash: "5 4" };
    default:
      return { stroke: stateColor(state), width: 1, dash: "3 5" };
  }
}

/**
 * The noun for a stage's published total, pluralised.
 *
 * Returns null for a stage with no unit -- a stage whose number would be
 * meaningless on its own -- so no bare digits are ever drawn.
 */
function countLabel(node: FlowNode, count: number): string | null {
  if (!node.unit) return null;
  const noun = count === 1 ? node.unit[0] : node.unit[1];
  return `${count.toLocaleString("en-US")} ${noun}`;
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
          stroke={stateColor(state)}
          strokeWidth={1.5}
        />
        <path
          d={`M ${x - 3} ${y - 3} l 6 6 M ${x + 3} ${y - 3} l -6 6`}
          stroke={stateColor(state)}
          strokeWidth={1.6}
          strokeLinecap="round"
        />
      </g>
    );
  }

  if (state === "active") {
    return (
      <g>
        <circle cx={x} cy={y} r={11} fill={glowColor(state)} opacity={0.18} />
        <circle
          className="flow-node-ring"
          cx={x}
          cy={y}
          r={7}
          fill="none"
          stroke={glowColor(state)}
          strokeWidth={2}
          strokeDasharray="4 3"
          strokeLinecap="round"
        />
      </g>
    );
  }

  return (
    <circle
      cx={x}
      cy={y}
      r={5}
      fill="none"
      stroke={stateColor(state)}
      strokeWidth={1.5}
    />
  );
}

/** One stage box. Memoised so a parse progress tick re-renders one text node. */
const FlowNodeBox = memo(function FlowNodeBox({
  node,
  state,
  progress,
  count,
}: {
  node: FlowNode;
  state: NodeState;
  progress?: { processed: number; total: number };
  count?: number;
}) {
  const { stroke, width, dash } = nodeStroke(state);
  const x = node.cx - NODE_WIDTH / 2;
  const y = node.cy - NODE_HEIGHT / 2;
  const dimmed = state === "pending";

  // One footer line, shared by the running counter and the finished total: no
  // stage publishes both, and a box this size has room for one.
  const stat = progress
    ? `${progress.processed.toLocaleString("en-US")}/${progress.total.toLocaleString("en-US")}`
    : count === undefined
      ? null
      : countLabel(node, count);
  // The label rises to make room for the footer. That shift is part of the
  // same transition as the glyph and the colour, so it reads as the node
  // gaining a result rather than as the layout twitching.
  const hasFooter = stat !== null;

  return (
    <g>
      {/* The active node gets a soft plate behind it, which is what makes the
          working stage the focal point without moving anything. */}
      {state === "active" && (
        <rect
          x={x - 6}
          y={y - 6}
          width={NODE_WIDTH + 12}
          height={NODE_HEIGHT + 12}
          rx={10}
          fill="none"
          stroke={glowColor(state)}
          strokeWidth={1}
          opacity={0.35}
        />
      )}
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
      <StateGlyph state={state} x={x + 20} y={node.cy} />
      <text
        x={x + 38}
        y={hasFooter ? node.cy - 4 : node.cy + 4}
        fill={dimmed ? "var(--muted-foreground)" : "var(--foreground)"}
        fontSize={13}
        fontWeight={state === "active" ? 600 : 400}
      >
        {node.label}
      </text>
      {stat && (
        <text
          x={x + 38}
          y={node.cy + 12}
          fill="var(--muted-foreground)"
          fontSize={9}
        >
          {stat}
        </text>
      )}
    </g>
  );
});

/** A shockwave: an expanding ring announcing a stage settling into a state. */
interface Shockwave {
  key: string;
  node: string;
  failed: boolean;
}

/**
 * The flow graph.
 *
 * @param states - Current state of every stage.
 * @param live - Whether frames are still arriving. When false the graph
 *   settles rather than continuing to look busy, so a stalled run cannot
 *   present itself as a working one.
 * @returns The animated pipeline canvas plus a screen-reader summary.
 */
export default function IngestFlowCanvas({
  states,
  live = true,
  attempt = 1,
}: {
  states: StageStateMap;
  live?: boolean;
  /** Which run this is. A change means a retry, which replays the rewind. */
  attempt?: number;
}) {
  const reduced = useReducedMotion();
  const [comets, setComets] = useState<string[]>([]);
  const [shockwaves, setShockwaves] = useState<Shockwave[]>([]);
  const previous = useRef<StageStateMap>(states);
  const initialised = useRef(false);
  const waveCount = useRef(0);

  const complete = isComplete(states);

  useEffect(() => {
    // The first pass is the seeded state, not a transition: replaying a
    // celebration for every already-finished stage would be a burst of noise.
    if (!initialised.current) {
      initialised.current = true;
      previous.current = states;
      return;
    }

    const before = previous.current;
    previous.current = states;

    if (reduced || !live) return;

    const settled = NODES.filter(
      (node) =>
        before[node.id]?.state !== "done" && states[node.id]?.state === "done",
    );
    const broke = NODES.filter(
      (node) =>
        before[node.id]?.state !== "failed" &&
        states[node.id]?.state === "failed",
    );

    // Keyed on the edge becoming lit rather than on a node settling: an edge
    // out of a barrier lights when the *last* of its required stages lands,
    // which no single node transition identifies.
    const newlyLit = EDGES.filter(
      (edge) => !isLit(edge, before) && isLit(edge, states),
    ).map(edgeId);

    if (newlyLit.length > 0) {
      setComets((current) => [...current, ...newlyLit]);
    }

    if (settled.length > 0 || broke.length > 0) {
      waveCount.current += 1;
      const round = waveCount.current;
      setShockwaves((current) => [
        ...current,
        ...settled.map((node) => ({
          key: `${round}-${node.id}`,
          node: node.id,
          failed: false,
        })),
        ...broke.map((node) => ({
          key: `${round}-${node.id}`,
          node: node.id,
          failed: true,
        })),
      ]);
    }
  }, [states, reduced, live]);

  const stateOf = (id: string): NodeState => states[id]?.state ?? "pending";

  return (
    <div className="relative h-full w-full">
      <svg
        viewBox={`0 0 ${VIEWBOX.width} ${VIEWBOX.height}`}
        preserveAspectRatio="xMidYMid meet"
        className="h-full w-full"
        aria-hidden="true"
      >
        <defs>
          {/* One bloom pass over the whole lit layer, rather than a filter per
              element -- filters are the expensive part, not the geometry. */}
          <filter id="flow-bloom" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="3.5" result="bloom" />
            <feMerge>
              <feMergeNode in="bloom" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>

          <radialGradient id="flow-halo">
            <stop
              offset="0%"
              stopColor={glowColor("active")}
              stopOpacity="0.45"
            />
            <stop
              offset="100%"
              stopColor={glowColor("active")}
              stopOpacity="0"
            />
          </radialGradient>

          {/* A gradient per edge, running source -> target, so a lit edge
              visibly arrives in whatever state the next stage is in. */}
          {EDGES.map((edge) => {
            const id = edgeId(edge);
            const first = edge.points[0];
            const last = edge.points[edge.points.length - 1];
            return (
              <linearGradient
                key={`gradient-${id}`}
                id={`flow-edge-${id}`}
                gradientUnits="userSpaceOnUse"
                x1={first[0]}
                y1={first[1]}
                x2={last[0]}
                y2={last[1]}
              >
                {/* Full opacity at both ends. The gradient carries direction
                    by hue; carrying it by brightness as well made every edge
                    look murky along its first half. */}
                <stop offset="0%" stopColor={stateColor("done")} />
                <stop offset="100%" stopColor={edgeEndColor(edge, states)} />
              </linearGradient>
            );
          })}
        </defs>

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

        {/* Live edges: the source has finished but the target has not, so
            work is genuinely in flight along this connection. Particles run
            continuously -- and only while frames are still arriving. */}
        {live && (
          <g opacity={0.9}>
            {EDGES.map((edge) => {
              const flowing = isFlowing(edge, states);
              if (!flowing) return null;
              return (
                <path
                  key={`stream-${edgeId(edge)}`}
                  className={reduced ? undefined : "flow-stream"}
                  d={pathFromPoints(edge.points)}
                  fill="none"
                  stroke={glowColor("active")}
                  strokeWidth={2}
                  strokeLinecap="round"
                  opacity={0.7}
                />
              );
            })}
          </g>
        )}

        {/* Lit edges, drawn once when their source completes. The bloom comes
            off when the stream goes quiet, so a stalled run visibly settles. */}
        <g
          filter="url(#flow-bloom)"
          style={{ transition: "opacity 700ms ease-out" }}
          opacity={live ? 1 : 0.4}
        >
          {EDGES.map((edge, index) => {
            const lit = isLit(edge, states);
            if (!lit) return null;
            return (
              <motion.path
                key={`lit-${edgeId(edge)}`}
                className={complete && !reduced ? "flow-surge" : undefined}
                style={
                  complete && !reduced
                    ? { animationDelay: `${index * 45}ms` }
                    : undefined
                }
                d={pathFromPoints(edge.points)}
                fill="none"
                stroke={`url(#flow-edge-${edgeId(edge)})`}
                strokeWidth={edge.kind === "sidecar" ? 1.2 : 1.8}
                strokeDasharray={edge.kind === "sidecar" ? "4 4" : undefined}
                initial={reduced ? false : { pathLength: 0, opacity: 0.4 }}
                animate={{ pathLength: 1, opacity: 1 }}
                transition={{ duration: 0.55, ease: "easeOut" }}
              />
            );
          })}
        </g>

        {/* The halo behind the working node. */}
        {live && !reduced && (
          <g>
            {NODES.map((node) =>
              stateOf(node.id) === "active" ? (
                <circle
                  key={`halo-${node.id}`}
                  className="flow-halo"
                  cx={node.cx}
                  cy={node.cy}
                  r={NODE_WIDTH / 2}
                  fill="url(#flow-halo)"
                />
              ) : null,
            )}
          </g>
        )}

        {/* Shockwaves, one per stage that just settled or broke. */}
        <AnimatePresence>
          {shockwaves.map((wave) => {
            const node = NODES_BY_ID[wave.node];
            if (!node) return null;
            return (
              <motion.circle
                key={`wave-${wave.key}`}
                cx={node.cx}
                cy={node.cy}
                fill="none"
                stroke={wave.failed ? stateColor("failed") : glowColor("done")}
                strokeWidth={2}
                initial={{ r: 14, opacity: 0.75 }}
                animate={{ r: 62, opacity: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.8, ease: "easeOut" }}
                onAnimationComplete={() =>
                  setShockwaves((current) =>
                    current.filter((entry) => entry.key !== wave.key),
                  )
                }
              />
            );
          })}
        </AnimatePresence>

        {/* Comets: a streak travelling each edge whose source just completed. */}
        <AnimatePresence>
          {comets.map((id) => {
            const edge = EDGES.find((candidate) => edgeId(candidate) === id);
            if (!edge) return null;
            const length = pathLengthOf(edge.points);
            return (
              <motion.path
                key={`comet-${id}`}
                d={pathFromPoints(edge.points)}
                fill="none"
                stroke={glowColor("done")}
                strokeWidth={3}
                strokeLinecap="round"
                strokeDasharray={`${COMET_LENGTH} ${length + COMET_LENGTH}`}
                initial={{ strokeDashoffset: 0, opacity: 0 }}
                animate={{
                  strokeDashoffset: -(length + COMET_LENGTH),
                  opacity: [0, 1, 0.9, 0],
                }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.8, ease: "easeInOut" }}
                onAnimationComplete={() =>
                  setComets((current) =>
                    current.filter((entry) => entry !== id),
                  )
                }
              />
            );
          })}
        </AnimatePresence>

        {/* A retry wipes the board clean before the new attempt starts.
            Keyed on the attempt number rather than held in state: a new key
            remounts the element, which replays the animation exactly once. */}
        {attempt > 1 && !reduced && (
          <motion.rect
            key={`rewind-${attempt}`}
            x={0}
            y={0}
            width={VIEWBOX.width}
            height={VIEWBOX.height}
            fill="var(--background)"
            initial={{ opacity: 0 }}
            animate={{ opacity: [0, 0.75, 0] }}
            transition={{ duration: 0.5, ease: "easeInOut" }}
          />
        )}

        {/* Nodes. */}
        <g>
          {NODES.map((node) => (
            <FlowNodeBox
              key={node.id}
              node={node}
              state={stateOf(node.id)}
              progress={states[node.id]?.progress}
              count={states[node.id]?.count}
            />
          ))}
        </g>
      </svg>

      {/* The SVG is decorative; this is what a screen reader gets. Progress
          numbers are deliberately excluded -- a ten-thousand-file parse would
          otherwise announce hundreds of times over -- but a stage's total
          arrives once, so it rides along with the state change rather than
          adding an announcement of its own. */}
      <ol className="sr-only" aria-live="polite" aria-atomic="false">
        {NODES.map((node) => {
          const total = states[node.id]?.count;
          const label = total === undefined ? null : countLabel(node, total);

          return (
            <li key={node.id}>
              {node.label}: {stateOf(node.id)}
              {label ? ` (${label})` : ""}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
