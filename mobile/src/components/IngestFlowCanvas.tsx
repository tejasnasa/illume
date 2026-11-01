/**
 * The ingestion pipeline drawn as an animated flow graph.
 *
 * @module IngestFlowCanvas
 *
 * Port of ``client/src/components/IngestFlowCanvas.tsx``.
 *
 * Every edge is authored geometry rather than a measured path, so the
 * travelling comet is driven by literal numbers and nothing has to be
 * re-measured on resize. That matters more here than it did on the web:
 * ``react-native-svg`` has no ``getTotalLength()`` and no ``pathLength``
 * attribute to normalise against, so the authored waypoints are the only
 * source of a path's length.
 *
 * **All motion runs on the UI thread.** The web version used CSS keyframes;
 * the same four keyframes (``flow-ring``, ``flow-stream``, ``flow-halo``,
 * ``flow-surge``) and the travelling comet are Reanimated worklets here.
 * There is deliberately no JavaScript frame loop: the graph has to sit on
 * screen for minutes at a time, and a per-frame JavaScript cost would be
 * paid for the whole of it.
 *
 * The graph is authored at 1210 x 580 -- a wide landscape shape that suits
 * the web's desktop viewport. On a phone it is drawn one-to-one and panned
 * horizontally, because scaling it down to fit would take the stage labels
 * below reading size. The header above the canvas carries the stage that is
 * running, in words, so the graph itself can stay a picture.
 */

import {
  memo,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
} from "react";
import { ScrollView, Text, View, type LayoutChangeEvent } from "react-native";
import Animated, {
  Easing,
  cancelAnimation,
  runOnJS,
  useAnimatedProps,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import Svg, {
  Circle,
  Defs,
  G,
  LinearGradient,
  Path,
  RadialGradient,
  Rect,
  Stop,
  Text as SvgText,
  type CircleProps,
  type PathProps,
  type RectProps,
} from "react-native-svg";

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
} from "@/lib/ingestFlow";
import { colors } from "@/theme/tokens";
import type { NodeState, StageStateMap } from "@/types/ingest";

/** Length of the travelling comet, in canvas units. */
const COMET_LENGTH = 30;

/** How long the comet takes to travel its edge, in milliseconds. */
const COMET_DURATION_MS = 800;

/** How long the comet takes to fade in, in milliseconds. */
const COMET_FADE_IN_MS = 200;

/** How long a lit edge takes to draw itself, in milliseconds. */
const LIT_DURATION_MS = 550;

/** How long a shockwave takes to expand, in milliseconds. */
const SHOCKWAVE_DURATION_MS = 800;

/** How long the retry wipe takes, in milliseconds. */
const REWIND_DURATION_MS = 500;

/** The dash pattern of the marching stream on an edge in flight. */
const STREAM_DASH = [4, 12] as const;

/** How far the stream's dashes travel per cycle. One pattern period. */
const STREAM_TRAVEL = 16;

/** How long the stream takes to travel one period, in milliseconds. */
const STREAM_DURATION_MS = 1100;

/** The dash pattern of the ring around the working node. */
const RING_DASH = [4, 3] as const;

/** How far the ring's dashes travel per cycle. Four pattern periods. */
const RING_TRAVEL = 28;

/** How long the ring takes to travel one cycle, in milliseconds. */
const RING_DURATION_MS = 1600;

/** How long the halo takes to swell and fade back, in milliseconds. */
const HALO_DURATION_MS = 2400;

/** How far the halo swells, as a fraction of its resting radius. */
const HALO_SWELL = 1.06;

/**
 * The luminous form of the active stage's colour.
 *
 * The brand's primary is dark (lightness 0.459), so used raw as a glow it
 * reads as a smudge rather than a light. Lifting the lightness keeps the
 * brand hue while making the working node the brightest thing on the
 * canvas -- otherwise the active stage would render dimmer than the finished
 * ones.
 *
 * This is ``oklch(0.78 0.187 3.815)``, which is the web client's
 * ``oklch(from var(--primary) 0.78 c h)`` written out: React Native's
 * colour parser understands neither the relative colour syntax nor oklch.
 */
const GLOW_ACTIVE = "#ff7daa";

/**
 * The animated SVG elements.
 *
 * Reanimated drives react-native-svg through props rather than styles, so
 * each element that moves has to be an animated component.
 */
const AnimatedPath = Animated.createAnimatedComponent(
  Path as unknown as ComponentType<PathProps>,
);
const AnimatedCircle = Animated.createAnimatedComponent(
  Circle as unknown as ComponentType<CircleProps>,
);
const AnimatedRect = Animated.createAnimatedComponent(
  Rect as unknown as ComponentType<RectProps>,
);

/** Stable identity for an edge. */
function edgeId(edge: FlowEdge): string {
  return `${edge.from}--${edge.to}`;
}

/**
 * The single place a node state maps to a colour.
 *
 * Border, glyph and edge gradient all read from here; when they drifted
 * apart the same node could show two different "active" colours at once.
 */
function stateColor(state: NodeState): string {
  switch (state) {
    case "done":
      return colors.success;
    case "active":
      return colors.primary;
    case "failed":
      return colors.destructive;
    default:
      return colors.border;
  }
}

/**
 * A luminous form of the state colour, for halos and glows.
 *
 * Only the active state gets a glow: the other states are already at or
 * near their natural brightness.
 */
function glowColor(state: NodeState): string {
  if (state === "active") return GLOW_ACTIVE;
  return stateColor(state);
}

/**
 * The colour a lit edge fades into at its far end.
 *
 * A barrier is not a stage, and a stage that has not started yet has no
 * colour of its own. Both used to fall back to the border colour, so the
 * line appeared to die partway along -- which reads as a rendering fault
 * rather than as anything about the pipeline. They fall back to the source
 * colour instead.
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
  dash?: readonly number[];
} {
  switch (state) {
    case "done":
      return { stroke: stateColor(state), width: 1.5 };
    case "active":
      return { stroke: stateColor(state), width: 2 };
    case "failed":
      return { stroke: stateColor(state), width: 2, dash: [5, 4] };
    default:
      return { stroke: stateColor(state), width: 1, dash: [3, 5] };
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

/**
 * The dashes marching along an edge that still has work in flight.
 *
 * The web version's ``flow-stream`` keyframe moved the dash offset by one
 * full pattern period, so the loop is seamless; the same numbers are used
 * here.
 */
function StreamingEdge({ edge }: { edge: FlowEdge }) {
  const offset = useSharedValue(0);

  useEffect(() => {
    offset.value = withRepeat(
      withTiming(STREAM_TRAVEL, {
        duration: STREAM_DURATION_MS,
        easing: Easing.linear,
      }),
      -1,
      false,
    );
    return () => cancelAnimation(offset);
  }, [offset]);

  const animatedProps = useAnimatedProps<PathProps>(() => ({
    strokeDashoffset: offset.value,
  }));

  return (
    <AnimatedPath
      testID={`ingest-stream-${edgeId(edge)}`}
      d={pathFromPoints(edge.points)}
      fill="none"
      stroke={glowColor("active")}
      strokeWidth={2}
      strokeLinecap="round"
      strokeDasharray={STREAM_DASH}
      opacity={0.7}
      animatedProps={animatedProps}
    />
  );
}

/**
 * The ring around the working node.
 *
 * The web version's ``flow-node-ring`` keyframe; the dashes march around
 * the ring rather than the ring rotating, which is the same read.
 */
function WorkingRing({ x, y }: { x: number; y: number }) {
  const offset = useSharedValue(0);

  useEffect(() => {
    offset.value = withRepeat(
      withTiming(RING_TRAVEL, {
        duration: RING_DURATION_MS,
        easing: Easing.linear,
      }),
      -1,
      false,
    );
    return () => cancelAnimation(offset);
  }, [offset]);

  const animatedProps = useAnimatedProps<CircleProps>(() => ({
    strokeDashoffset: offset.value,
  }));

  return (
    <AnimatedCircle
      cx={x}
      cy={y}
      r={7}
      fill="none"
      stroke={glowColor("active")}
      strokeWidth={2}
      strokeDasharray={RING_DASH}
      strokeLinecap="round"
      animatedProps={animatedProps}
    />
  );
}

/**
 * The halo behind the working node.
 *
 * The web version's ``flow-halo`` keyframe swelled the circle and breathed
 * its opacity. A group has no animatable geometry on native, so the swell
 * is expressed as a growing radius instead -- the same picture, drawn with
 * the one number the platform can move.
 */
function WorkingHalo({ node }: { node: FlowNode }) {
  const radius = useSharedValue(NODE_WIDTH / 2);
  const opacity = useSharedValue(0.28);

  useEffect(() => {
    const half = HALO_DURATION_MS / 2;
    radius.value = withRepeat(
      withSequence(
        withTiming((NODE_WIDTH / 2) * HALO_SWELL, {
          duration: half,
          easing: Easing.inOut(Easing.ease),
        }),
        withTiming(NODE_WIDTH / 2, {
          duration: half,
          easing: Easing.inOut(Easing.ease),
        }),
      ),
      -1,
      false,
    );
    opacity.value = withRepeat(
      withSequence(
        withTiming(0.55, { duration: half, easing: Easing.inOut(Easing.ease) }),
        withTiming(0.28, { duration: half, easing: Easing.inOut(Easing.ease) }),
      ),
      -1,
      false,
    );
    return () => {
      cancelAnimation(radius);
      cancelAnimation(opacity);
    };
  }, [radius, opacity]);

  const animatedProps = useAnimatedProps<CircleProps>(() => ({
    r: radius.value,
    opacity: opacity.value,
  }));

  return (
    <AnimatedCircle
      testID={`ingest-halo-${node.id}`}
      cx={node.cx}
      cy={node.cy}
      r={NODE_WIDTH / 2}
      fill="url(#flow-halo)"
      animatedProps={animatedProps}
    />
  );
}

/**
 * A streak travelling an edge whose source has just completed.
 *
 * The web version drew the streak as a dash on the edge's own path and
 * moved the dash offset along it. The dash pattern is the edge's own
 * length, so the streak covers exactly the edge and nothing has to be
 * measured.
 */
function Comet({ edge, onDone }: { edge: FlowEdge; onDone: () => void }) {
  const length = pathLengthOf(edge.points);
  const offset = useSharedValue(0);
  const opacity = useSharedValue(0);

  useEffect(() => {
    offset.value = withTiming(
      -(length + COMET_LENGTH),
      { duration: COMET_DURATION_MS, easing: Easing.inOut(Easing.ease) },
      (finished) => {
        if (finished) runOnJS(onDone)();
      },
    );
    opacity.value = withSequence(
      withTiming(1, {
        duration: COMET_FADE_IN_MS,
        easing: Easing.linear,
      }),
      withTiming(0.9, { duration: 120, easing: Easing.linear }),
      withTiming(0, {
        duration: COMET_DURATION_MS - COMET_FADE_IN_MS - 120,
        easing: Easing.linear,
      }),
    );
    return () => {
      cancelAnimation(offset);
      cancelAnimation(opacity);
    };
    // The animation runs once, when the streak appears.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const animatedProps = useAnimatedProps<PathProps>(() => ({
    strokeDashoffset: offset.value,
    opacity: opacity.value,
  }));

  return (
    <AnimatedPath
      testID={`ingest-comet-${edgeId(edge)}`}
      d={pathFromPoints(edge.points)}
      fill="none"
      stroke={glowColor("done")}
      strokeWidth={3}
      strokeLinecap="round"
      strokeDasharray={[COMET_LENGTH, length + COMET_LENGTH]}
      animatedProps={animatedProps}
    />
  );
}

/**
 * A shockwave: an expanding ring announcing a stage settling into a state.
 */
function Shockwave({
  node,
  failed,
  onDone,
}: {
  node: FlowNode;
  failed: boolean;
  onDone: () => void;
}) {
  const radius = useSharedValue(14);
  const opacity = useSharedValue(0.75);

  useEffect(() => {
    radius.value = withTiming(
      62,
      { duration: SHOCKWAVE_DURATION_MS, easing: Easing.out(Easing.ease) },
      (finished) => {
        if (finished) runOnJS(onDone)();
      },
    );
    opacity.value = withTiming(0, {
      duration: SHOCKWAVE_DURATION_MS,
      easing: Easing.out(Easing.ease),
    });
    return () => {
      cancelAnimation(radius);
      cancelAnimation(opacity);
    };
    // The animation runs once, when the wave appears.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const animatedProps = useAnimatedProps<CircleProps>(() => ({
    r: radius.value,
    opacity: opacity.value,
  }));

  return (
    <AnimatedCircle
      testID={`ingest-shockwave-${node.id}`}
      cx={node.cx}
      cy={node.cy}
      fill="none"
      stroke={failed ? stateColor("failed") : glowColor("done")}
      strokeWidth={2}
      animatedProps={animatedProps}
    />
  );
}

/**
 * A lit edge.
 *
 * The web version drew the edge on from nothing using the motion library's
 * ``pathLength``, which normalises a path to a 0..1 range. Native has no
 * such attribute, so the edge is drawn on with a dash pattern the length of
 * the edge itself and an offset that slides from "all gap" to "all dash".
 *
 * A sidecar edge keeps its own dash pattern -- it is a rail, not a trunk --
 * so it fades in rather than drawing on.
 */
function LitEdge({
  edge,
  index,
  complete,
  reduced,
}: {
  edge: FlowEdge;
  index: number;
  complete: boolean;
  reduced: boolean;
}) {
  const length = pathLengthOf(edge.points);
  const sidecar = edge.kind === "sidecar";
  const baseWidth = sidecar ? 1.2 : 1.8;

  const draw = useSharedValue(reduced ? 1 : 0);
  const drawOpacity = useSharedValue(reduced ? 1 : 0.4);
  const surgeOpacity = useSharedValue(0.55);
  const surgeWidth = useSharedValue(2);

  useEffect(() => {
    if (reduced) return;
    draw.value = withTiming(1, {
      duration: LIT_DURATION_MS,
      easing: Easing.out(Easing.ease),
    });
    drawOpacity.value = withTiming(1, {
      duration: LIT_DURATION_MS,
      easing: Easing.out(Easing.ease),
    });
  }, [draw, drawOpacity, reduced]);

  // The surge: the web version's ``flow-surge`` keyframe, a one-shot
  // flourish played across every lit edge once the whole run finishes.
  const [surging, setSurging] = useState(false);
  useEffect(() => {
    if (!complete || reduced) return;
    setSurging(true);
    const delay = index * 45;
    surgeOpacity.value = withDelay(
      delay,
      withSequence(
        withTiming(0.55, { duration: 1, easing: Easing.linear }),
        withTiming(1, { duration: 280, easing: Easing.linear }),
        withTiming(1, { duration: 420, easing: Easing.linear }),
      ),
    );
    surgeWidth.value = withDelay(
      delay,
      withSequence(
        withTiming(2, { duration: 1, easing: Easing.linear }),
        withTiming(3.5, { duration: 280, easing: Easing.linear }),
        withTiming(baseWidth, { duration: 420, easing: Easing.linear }),
      ),
    );
  }, [complete, reduced, index, surgeOpacity, surgeWidth, baseWidth]);

  // The dash pattern is the edge's own length, so the line is revealed by
  // sliding the pattern rather than by measuring anything. A point of slack
  // keeps the far end from ending in a hairline gap.
  const dash = length + 1;

  const animatedProps = useAnimatedProps<PathProps>(() => ({
    strokeDashoffset: sidecar ? 0 : dash * (1 - draw.value),
    opacity: surging ? surgeOpacity.value : drawOpacity.value,
    strokeWidth: surging ? surgeWidth.value : baseWidth,
  }));

  return (
    <AnimatedPath
      testID={`ingest-lit-${edgeId(edge)}`}
      d={pathFromPoints(edge.points)}
      fill="none"
      stroke={`url(#flow-edge-${edgeId(edge)})`}
      strokeDasharray={sidecar ? [4, 4] : [dash, dash]}
      animatedProps={animatedProps}
    />
  );
}

/**
 * A retry wipes the board clean before the new attempt starts.
 *
 * Keyed on the attempt number rather than held in state: a new key remounts
 * the element, which replays the animation exactly once.
 */
function Rewind({ attempt }: { attempt: number }) {
  const opacity = useSharedValue(0);

  useEffect(() => {
    opacity.value = withSequence(
      withTiming(0.75, {
        duration: REWIND_DURATION_MS / 2,
        easing: Easing.inOut(Easing.ease),
      }),
      withTiming(0, {
        duration: REWIND_DURATION_MS / 2,
        easing: Easing.inOut(Easing.ease),
      }),
    );
  }, [attempt, opacity]);

  const animatedProps = useAnimatedProps<RectProps>(() => ({
    opacity: opacity.value,
  }));

  return (
    <AnimatedRect
      x={0}
      y={0}
      width={VIEWBOX.width}
      height={VIEWBOX.height}
      fill={colors.background}
      animatedProps={animatedProps}
    />
  );
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
      <G>
        <Circle cx={x} cy={y} r={7} fill={colors.success} />
        <Path
          d={`M ${x - 3.2} ${y} L ${x - 0.8} ${y + 2.4} L ${x + 3.4} ${y - 2.2}`}
          fill="none"
          stroke={colors.background}
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </G>
    );
  }

  if (state === "failed") {
    return (
      <G>
        <Circle
          cx={x}
          cy={y}
          r={7}
          fill="none"
          stroke={stateColor(state)}
          strokeWidth={1.5}
        />
        <Path
          d={`M ${x - 3} ${y - 3} L ${x + 3} ${y + 3} M ${x + 3} ${y - 3} L ${x - 3} ${y + 3}`}
          stroke={stateColor(state)}
          strokeWidth={1.6}
          strokeLinecap="round"
        />
      </G>
    );
  }

  if (state === "active") {
    return (
      <G>
        <Circle cx={x} cy={y} r={11} fill={glowColor(state)} opacity={0.18} />
        <WorkingRing x={x} y={y} />
      </G>
    );
  }

  return (
    <Circle
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
    <G>
      {/* The active node gets a soft plate behind it, which is what makes the
          working stage the focal point without moving anything. */}
      {state === "active" ? (
        <Rect
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
      ) : null}
      <Rect
        x={x}
        y={y}
        width={NODE_WIDTH}
        height={NODE_HEIGHT}
        rx={6}
        fill={colors.card}
        stroke={stroke}
        strokeWidth={width}
        strokeDasharray={dash}
      />
      <StateGlyph state={state} x={x + 20} y={node.cy} />
      <SvgText
        x={x + 38}
        y={hasFooter ? node.cy - 4 : node.cy + 4}
        fill={dimmed ? colors.mutedForeground : colors.foreground}
        fontSize={13}
        fontWeight={state === "active" ? 600 : 400}
      >
        {node.label}
      </SvgText>
      {stat ? (
        <SvgText
          x={x + 38}
          y={node.cy + 12}
          fill={colors.mutedForeground}
          fontSize={9}
        >
          {stat}
        </SvgText>
      ) : null}
    </G>
  );
});

/** A shockwave waiting to be drawn. */
interface ShockwaveEntry {
  key: string;
  node: string;
  failed: boolean;
}

/** Props for {@link IngestFlowCanvas}. */
export interface IngestFlowCanvasProps {
  /** Current state of every stage. */
  states: StageStateMap;
  /**
   * Whether frames are still arriving. When false the graph settles rather
   * than continuing to look busy, so a stalled run cannot present itself as
   * a working one.
   */
  live?: boolean;
  /** Which run this is. A change means a retry, which replays the rewind. */
  attempt?: number;
  /**
   * Whether the reader has asked for less motion. When true the graph
   * renders its finished state and nothing moves.
   */
  reducedMotion?: boolean;
}

/**
 * The flow graph.
 *
 * @param props - The stage states and the run's liveliness.
 * @returns The animated pipeline canvas.
 */
export function IngestFlowCanvas({
  states,
  live = true,
  attempt = 1,
  reducedMotion = false,
}: IngestFlowCanvasProps) {
  const [comets, setComets] = useState<string[]>([]);
  const [shockwaves, setShockwaves] = useState<ShockwaveEntry[]>([]);
  const previous = useRef<StageStateMap>(states);
  const initialised = useRef(false);
  const waveCount = useRef(0);

  // The graph is authored at a fixed size; it is scaled down only when the
  // viewport is too short to show it, and never scaled up.
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const scale =
    viewport.height > 0 ? Math.min(1, viewport.height / VIEWBOX.height) : 1;
  const canvasWidth = VIEWBOX.width * scale;
  const canvasHeight = VIEWBOX.height * scale;
  const pannable = viewport.width > 0 && canvasWidth > viewport.width + 1;

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

    if (reducedMotion || !live) return;

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
  }, [states, reducedMotion, live]);

  const stateOf = (id: string): NodeState => states[id]?.state ?? "pending";

  const litEdges = useMemo(
    () => EDGES.filter((edge) => isLit(edge, states)),
    [states],
  );
  const flowingEdges = useMemo(
    () => EDGES.filter((edge) => isFlowing(edge, states)),
    [states],
  );
  const activeNodes = useMemo(
    () => NODES.filter((node) => stateOf(node.id) === "active"),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [states],
  );

  const summary = useMemo(
    () => NODES.map((node) => `${node.label}: ${stateOf(node.id)}`).join(", "),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [states],
  );

  /**
   * Record the size of the area the canvas has to live in.
   *
   * @param event - The layout event.
   */
  const handleLayout = (event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    setViewport((current) =>
      current.width === width && current.height === height
        ? current
        : { width, height },
    );
  };

  /**
   * Drop a comet once it has travelled its edge.
   *
   * @param id - The edge the comet was travelling.
   */
  const dropComet = (id: string) => {
    setComets((current) => current.filter((entry) => entry !== id));
  };

  /**
   * Drop a shockwave once it has expanded.
   *
   * @param key - The wave's identity.
   */
  const dropShockwave = (key: string) => {
    setShockwaves((current) => current.filter((entry) => entry.key !== key));
  };

  return (
    <View
      testID="ingest-flow-canvas"
      onLayout={handleLayout}
      style={styles.root}
    >
      <ScrollView
        testID="ingest-flow-scroll"
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.scrollContent}
      >
        <Svg
          testID="ingest-flow-svg"
          width={canvasWidth}
          height={canvasHeight}
          viewBox={`0 0 ${VIEWBOX.width} ${VIEWBOX.height}`}
          accessibilityLabel={`Ingestion pipeline. ${summary}`}
        >
          <Defs>
            <RadialGradient id="flow-halo" cx="50%" cy="50%" r="50%">
              <Stop offset="0%" stopColor={GLOW_ACTIVE} stopOpacity={0.45} />
              <Stop offset="100%" stopColor={GLOW_ACTIVE} stopOpacity={0} />
            </RadialGradient>

            {/* A gradient per edge, running source -> target, so a lit edge
                visibly arrives in whatever state the next stage is in. */}
            {EDGES.map((edge) => {
              const first = edge.points[0];
              const last = edge.points[edge.points.length - 1];
              return (
                <LinearGradient
                  key={`gradient-${edgeId(edge)}`}
                  id={`flow-edge-${edgeId(edge)}`}
                  gradientUnits="userSpaceOnUse"
                  x1={first[0]}
                  y1={first[1]}
                  x2={last[0]}
                  y2={last[1]}
                >
                  {/* Full opacity at both ends. The gradient carries direction
                      by hue; carrying it by brightness as well made every
                      edge look murky along its first half. */}
                  <Stop offset="0%" stopColor={stateColor("done")} />
                  <Stop offset="100%" stopColor={edgeEndColor(edge, states)} />
                </LinearGradient>
              );
            })}
          </Defs>

          {/* Base edges: always present, so the graph reads before anything
              runs. */}
          <G>
            {EDGES.map((edge) => (
              <Path
                key={`base-${edgeId(edge)}`}
                d={pathFromPoints(edge.points)}
                fill="none"
                stroke={colors.border}
                strokeWidth={edge.kind === "sidecar" ? 1 : 1.5}
                strokeDasharray={edge.kind === "sidecar" ? [4, 4] : undefined}
              />
            ))}
          </G>

          {/* Live edges: the source has finished but the target has not, so
              work is genuinely in flight along this connection. Particles run
              continuously -- and only while frames are still arriving. */}
          {live ? (
            <G opacity={0.9}>
              {flowingEdges.map((edge) => (
                <StreamingEdge key={`stream-${edgeId(edge)}`} edge={edge} />
              ))}
            </G>
          ) : null}

          {/* Lit edges, drawn once when their source completes. */}
          <G opacity={live ? 1 : 0.4}>
            {litEdges.map((edge, index) => (
              <LitEdge
                key={`lit-${edgeId(edge)}`}
                edge={edge}
                index={index}
                complete={complete}
                reduced={reducedMotion}
              />
            ))}
          </G>

          {/* The halo behind the working node. */}
          {live && !reducedMotion ? (
            <G>
              {activeNodes.map((node) => (
                <WorkingHalo key={`halo-${node.id}`} node={node} />
              ))}
            </G>
          ) : null}

          {/* Shockwaves, one per stage that just settled or broke. */}
          {reducedMotion
            ? null
            : shockwaves.map((wave) => {
                const node = NODES_BY_ID[wave.node];
                if (!node) return null;
                return (
                  <Shockwave
                    key={`wave-${wave.key}`}
                    node={node}
                    failed={wave.failed}
                    onDone={() => dropShockwave(wave.key)}
                  />
                );
              })}

          {/* Comets: a streak travelling each edge whose source just
              completed. */}
          {reducedMotion
            ? null
            : comets.map((id) => {
                const edge = EDGES.find(
                  (candidate) => edgeId(candidate) === id,
                );
                if (!edge) return null;
                return (
                  <Comet
                    key={`comet-${id}`}
                    edge={edge}
                    onDone={() => dropComet(id)}
                  />
                );
              })}

          {/* A retry wipes the board clean before the new attempt starts. */}
          {attempt > 1 && !reducedMotion ? (
            <Rewind key={`rewind-${attempt}`} attempt={attempt} />
          ) : null}

          {/* Nodes. */}
          <G>
            {NODES.map((node) => (
              <FlowNodeBox
                key={node.id}
                node={node}
                state={stateOf(node.id)}
                progress={states[node.id]?.progress}
                count={states[node.id]?.count}
              />
            ))}
          </G>
        </Svg>
      </ScrollView>

      {pannable ? (
        <View
          testID="ingest-flow-pan-hint"
          pointerEvents="none"
          style={styles.panHint}
        >
          <Text className="text-[10px] text-muted-foreground">
            Swipe the canvas to follow the pipeline →
          </Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = {
  root: { flex: 1, overflow: "hidden" as const },
  scrollContent: {
    alignItems: "center" as const,
    justifyContent: "flex-start" as const,
  },
  panHint: {
    position: "absolute" as const,
    right: 8,
    bottom: 6,
  },
};

export default IngestFlowCanvas;
