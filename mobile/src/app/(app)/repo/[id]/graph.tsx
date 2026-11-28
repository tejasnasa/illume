/**
 * The dependency graph screen.
 *
 * @module GraphScreen
 *
 * The web client draws the graph in a full-page canvas with the search
 * box, the legend, the level switch and the reading-order tour floating
 * over it. The same four controls sit over the canvas here, arranged for a
 * phone: the level switch and the tour at the top, the search at the
 * bottom, and the legend tucked under the level switch.
 *
 * The graph is fetched, laid out, and then drawn. The layout is the slow
 * part -- a large repository is tens of thousands of nodes -- so it reports
 * progress rather than showing an empty screen for a minute.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  AppState,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import {
  router,
  useGlobalSearchParams,
  useIsFocused,
  type Href,
} from "expo-router";
import { useQuery } from "@tanstack/react-query";

import { getGraph, type GraphLevel } from "@/api/graph";
import { ApiError } from "@/lib/apiError";
import { RenderBoundary } from "@/components/RenderBoundary";
import type { GraphPayload } from "@/lib/graphTypes";
import { queryKeys } from "@/api/queryKeys";
import { GraphInspector } from "@/components/GraphInspector";
import {
  GraphRenderer,
  type GraphRendererHandle,
} from "@/components/GraphRenderer";
import { useRepository } from "@/hooks/useRepositories";
import { useRepositoryGuide } from "@/hooks/useRepoGuide";
import { computeLayout, type LayoutResult } from "@/lib/graphLayout";
import {
  guideSteps,
  matchNodes,
  neighboursOf,
  nodeIndexById,
} from "@/lib/graphSelection";
import { nextTourIndex, TOUR_STEP_MS } from "@/lib/graphTour";
import { isReadyStatus } from "@/lib/repoStatus";
import { colors } from "@/theme/tokens";

/** The levels the graph can be drawn at. */
const LEVELS: readonly { value: GraphLevel; label: string }[] = [
  { value: "file", label: "Files" },
  { value: "symbol", label: "Symbols" },
];

/** The legend: every colour the graph uses and what it means. */
const LEGEND = [
  { color: "#ef4444", label: "Critical" },
  { color: "#facc15", label: "Caution" },
  { color: "#22c55e", label: "Safe" },
  { color: "#0078ff", label: "Selected" },
  { color: "#a855f7", label: "Match" },
] as const;

/**
 * The route-level fallback. A render error anywhere in this screen lands
 * here, inside the repository shell, instead of closing the app.
 *
 * @param props - The error and the retry the router offers.
 * @returns The fallback.
 */
export function ErrorBoundary({
  error,
  retry,
}: {
  error: Error;
  retry: () => void;
}) {
  return (
    <View
      testID="graph-error-boundary"
      className="flex-1 items-center justify-center bg-background p-6"
    >
      <Text className="mb-2 text-base font-semibold text-destructive">
        The graph stopped working
      </Text>
      <Text className="mb-4 text-center text-[13px] text-muted-foreground">
        {error?.message ?? "An unexpected error stopped this screen."}
      </Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Try again"
        onPress={retry}
        className="min-h-[44px] justify-center rounded bg-primary px-5"
      >
        <Text className="text-sm font-semibold text-primary-foreground">
          Try again
        </Text>
      </Pressable>
    </View>
  );
}

/**
 * Message for a graph request that failed.
 *
 * @param error - What the query threw.
 * @returns Text for the reader.
 */
export function graphErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return "This repository is still being analysed. Open the graph again once it is ready.";
  }
  if (error instanceof ApiError && error.status === 404) {
    return "This repository could not be found.";
  }
  return "The graph could not be loaded.";
}

/**
 * Whether the app is in the foreground.
 *
 * @returns True while the app state is `active`.
 */
function useAppActive(): boolean {
  const [active, setActive] = useState(AppState.currentState !== "background");
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (status) => {
      setActive(status === "active");
    });
    return () => subscription.remove();
  }, []);
  return active;
}

/**
 * Render the dependency graph.
 *
 * @returns The graph screen.
 */
export default function GraphScreen() {
  // ``useGlobalSearchParams``, not the local variant: these screens are
  // tab children, not the ``[id]`` segment itself, and a local lookup
  // only sees the current route's own params -- which is why every
  // screen here used to receive an empty id and render nothing.
  const { id } = useGlobalSearchParams<{ id: string }>();
  const repoNumber = String(id ?? "");
  // The GL surface lives only while the graph is on screen. Android destroys
  // the surface behind a hidden tab or a backgrounded app; unmounting the
  // renderer first means its scene is never drawn against a dead context,
  // and coming back builds a fresh one from the layout kept in state.
  const focused = useIsFocused();
  const appActive = useAppActive();
  const drawing = focused && appActive;

  const { data: repo } = useRepository(repoNumber);
  const { data: guide } = useRepositoryGuide(
    repo?.id,
    isReadyStatus(repo?.status),
  );

  const [level, setLevel] = useState<GraphLevel>("file");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tourIndex, setTourIndex] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  // The layout is kept with the payload it was computed from. The renderer
  // builds its scene once, so it must always be handed nodes and positions
  // that belong together; during a level switch the query holds no payload
  // and a separate layout would be paired with an empty node list.
  const [laidOut, setLaidOut] = useState<{
    graph: GraphPayload;
    layout: LayoutResult;
  } | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const [layoutProgress, setLayoutProgress] = useState(0);
  const layout = laidOut?.layout ?? null;

  const rendererRef = useRef<GraphRendererHandle>(null);

  const {
    data: graph,
    isLoading,
    isError,
    error: queryError,
  } = useQuery({
    queryKey: queryKeys.repositories.graph(repo?.id ?? "", level),
    queryFn: () => getGraph(repo?.id as string, level),
    enabled: Boolean(repo?.id),
  });

  // The layout is a simulation, and it is the slow part of drawing a large
  // repository. It is chunked, so the progress it reports is real -- but
  // the report is throttled, because the screen re-renders on every change
  // and a layout of thousands of nodes produces a change every few
  // milliseconds.
  const lastReportedProgress = useRef(0);

  useEffect(() => {
    if (!graph) return;
    let cancelled = false;
    // Aborting between ticks is what stops a large layout from continuing to
    // burn CPU after the reader has left or switched level.
    const controller = new AbortController();
    setLaidOut(null);
    setLayoutError(null);
    setLayoutProgress(0);
    setSelectedId(null);
    setTourIndex(null);
    lastReportedProgress.current = 0;

    void computeLayout(graph, {
      signal: controller.signal,
      onProgress: (done, total) => {
        if (cancelled) return;
        const fraction = total > 0 ? done / total : 0;
        if (fraction - lastReportedProgress.current < 0.05) return;
        lastReportedProgress.current = fraction;
        setLayoutProgress(fraction);
      },
    })
      .then((result) => {
        if (!cancelled) setLaidOut({ graph, layout: result });
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setLayoutError(
          cause instanceof Error ? cause.message : "The layout failed.",
        );
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [graph]);

  const matches = useMemo(
    () => matchNodes(graph?.nodes ?? [], query),
    [graph, query],
  );
  const matchIds = useMemo(() => matches.map((node) => node.id), [matches]);

  const steps = useMemo(
    () => guideSteps(guide?.reading_order ?? [], graph?.nodes ?? []),
    [guide, graph],
  );

  const selectedNode = useMemo(
    () => graph?.nodes.find((node) => node.id === selectedId) ?? null,
    [graph, selectedId],
  );

  const selectedAnnotation = useMemo(() => {
    if (!selectedNode) return null;
    const entry = guide?.reading_order?.find(
      (item) => item.file_path === selectedNode.path,
    );
    return entry?.annotation ?? null;
  }, [guide, selectedNode]);

  const neighbours = useMemo(() => {
    if (!laidOut || !selectedNode) return { importers: [], imports: [] };
    return neighboursOf(
      laidOut.graph.nodes,
      laidOut.layout.links,
      nodeIndexById(laidOut.graph.nodes, selectedNode.id),
    );
  }, [laidOut, selectedNode]);

  const selectedTourPosition = useMemo(() => {
    if (!selectedNode) return null;
    const at = steps.findIndex((step) => step.node.id === selectedNode.id);
    return at === -1 ? null : at + 1;
  }, [steps, selectedNode]);

  /**
   * Move the tour to a step and focus the node it names.
   *
   * @param index - The step to move to.
   */
  const goToStep = (index: number) => {
    const step = steps[index];
    if (!step) return;
    setTourIndex(index);
    setSelectedId(step.node.id);
    rendererRef.current?.focusNode(step.node.id);
  };

  // Playing the tour advances a step every few seconds and stops at the end.
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      setTourIndex((current) => {
        const next = nextTourIndex(current, steps.length);
        if (next === null) {
          setPlaying(false);
          return current;
        }
        const step = steps[next];
        setSelectedId(step.node.id);
        rendererRef.current?.focusNode(step.node.id);
        return next;
      });
    }, TOUR_STEP_MS);
    return () => clearInterval(timer);
  }, [playing, steps]);

  if (isError || layoutError) {
    return (
      <View
        testID="graph-error"
        className="flex-1 items-center justify-center bg-background p-6"
      >
        <Text className="text-center text-[13px] text-muted-foreground">
          {layoutError ?? graphErrorMessage(queryError)}
        </Text>
      </View>
    );
  }

  const nodeTotal = Array.isArray(graph?.nodes) ? graph.nodes.length : 0;
  const isEmpty = Boolean(graph) && nodeTotal === 0;
  const busy = isLoading || (Boolean(graph) && !isEmpty && !layout);

  return (
    <View className="flex-1">
      {isEmpty ? (
        <View
          testID="graph-empty"
          className="flex-1 items-center justify-center p-6"
        >
          <Text className="text-center text-[13px] text-muted-foreground">
            There is nothing to draw at this level yet.
          </Text>
        </View>
      ) : null}

      {drawing && laidOut && laidOut.layout.nodeCount > 0 ? (
        <RenderBoundary title="The graph could not be drawn">
          <GraphRenderer
            key={`${level}-${laidOut.layout.nodeCount}`}
            ref={rendererRef}
            positions={laidOut.layout.positions}
            links={laidOut.layout.links}
            nodes={laidOut.graph.nodes.slice(0, laidOut.layout.nodeCount)}
            boundingRadius={laidOut.layout.boundingRadius}
            selectedNodeId={selectedId}
            matchNodeIds={matchIds}
            onSelect={(nodeId) => {
              setSelectedId(nodeId);
              if (nodeId === null) setTourIndex(null);
            }}
          />
        </RenderBoundary>
      ) : null}

      {laidOut?.layout.truncated ? (
        <View
          testID="graph-truncated"
          className="absolute left-3 right-3 top-24 rounded border border-border bg-background/90 px-3 py-2"
        >
          <Text className="text-[11px] text-muted-foreground">
            Showing the first {laidOut.layout.nodeCount} of {nodeTotal} nodes.
          </Text>
        </View>
      ) : null}

      {busy ? (
        <View
          testID="graph-loading"
          className="absolute inset-0 items-center justify-center bg-background"
        >
          <ActivityIndicator size="large" color={colors.foreground} />
          <Text className="mt-3 text-xs text-muted-foreground">
            {isLoading
              ? "Loading the graph…"
              : `Laying out ${graph?.nodes.length ?? 0} nodes… ${Math.round(
                  layoutProgress * 100,
                )}%`}
          </Text>
        </View>
      ) : null}

      {/*
        The chrome floats over the canvas: the level switch and the legend
        on top, the reading-order tour under them, the search at the bottom.
        No safe-area inset on top: the repository shell has already applied
        it above the tab bar.
      */}
      <View className="absolute left-3 right-3 top-2" pointerEvents="box-none">
        <View className="flex-row items-start justify-between" pointerEvents="box-none">
          <View className="flex-row rounded-sm border border-border bg-card/90">
            {LEVELS.map((entry) => {
              const active = level === entry.value;
              return (
                <Pressable
                  key={entry.value}
                  testID={`graph-level-${entry.value}`}
                  accessibilityRole="button"
                  accessibilityState={{ selected: active }}
                  accessibilityLabel={`${entry.label} level`}
                  onPress={() => {
                    setPlaying(false);
                    setLevel(entry.value);
                  }}
                  className={`min-h-[40px] justify-center px-3.5 ${
                    active ? "bg-primary" : "bg-transparent"
                  }`}
                >
                  <Text
                    className={`font-pixel text-xs uppercase tracking-[1px] ${
                      active ? "text-primary-foreground" : "text-muted-foreground"
                    }`}
                  >
                    {entry.label}
                  </Text>
                </Pressable>
              );
            })}
          </View>

          <View testID="graph-legend" className="rounded-sm border border-border bg-card/90 px-2.5 py-1.5">
            {LEGEND.filter((entry) => entry.label !== "Match" || query.trim()).map(
              (entry) => (
                <View key={entry.label} className="flex-row items-center gap-2 py-0.5">
                  <View style={{ width: 8, height: 8, backgroundColor: entry.color }} />
                  <Text className="font-pixel text-[10px] uppercase tracking-[0.8px] text-muted-foreground">
                    {entry.label}
                    {entry.label === "Match" ? ` (${matches.length})` : ""}
                  </Text>
                </View>
              ),
            )}
          </View>
        </View>

        {level === "file" && steps.length > 0 ? (
          <View
            testID="graph-tour"
            className="mt-2 flex-row items-center gap-2 self-start rounded-sm border border-border bg-card/90 px-2 py-1.5"
          >
            <Text className="font-pixel text-[10px] uppercase tracking-[1px] text-foreground">
              Reading order
            </Text>
            <Pressable
              testID="graph-tour-previous"
              accessibilityRole="button"
              accessibilityLabel="Previous step"
              accessibilityState={{ disabled: tourIndex === null || tourIndex === 0 }}
              onPress={() => {
                setPlaying(false);
                goToStep((tourIndex ?? 0) - 1);
              }}
              disabled={tourIndex === null || tourIndex === 0}
              className="min-h-[36px] min-w-[36px] items-center justify-center rounded-sm border border-border px-2 active:border-accent disabled:opacity-30"
            >
              <Text className="font-pixel text-sm text-foreground">‹</Text>
            </Pressable>
            <Pressable
              testID="graph-tour-play"
              accessibilityRole="button"
              accessibilityLabel={playing ? "Pause the tour" : "Play the tour"}
              accessibilityState={{ selected: playing }}
              onPress={() => {
                if (!playing && (tourIndex === null || tourIndex >= steps.length - 1)) {
                  goToStep(0);
                }
                setPlaying((v) => !v);
              }}
              className="min-h-[36px] min-w-[36px] items-center justify-center rounded-sm border border-border px-2 active:border-accent"
            >
              <Text className="font-pixel text-sm text-accent">{playing ? "❚❚" : "▶"}</Text>
            </Pressable>
            <Pressable
              testID="graph-tour-next"
              accessibilityRole="button"
              accessibilityLabel="Next step"
              accessibilityState={{
                disabled: tourIndex !== null && tourIndex === steps.length - 1,
              }}
              onPress={() => {
                setPlaying(false);
                goToStep((tourIndex ?? -1) + 1);
              }}
              disabled={tourIndex !== null && tourIndex === steps.length - 1}
              className="min-h-[36px] min-w-[36px] items-center justify-center rounded-sm border border-border px-2 active:border-accent disabled:opacity-30"
            >
              <Text className="font-pixel text-sm text-foreground">›</Text>
            </Pressable>
            <Text className="font-pixel text-[11px] text-muted-foreground">
              {tourIndex === null ? "—" : tourIndex + 1} / {steps.length}
            </Text>
          </View>
        ) : null}
      </View>

      {/* The search box, with the number of matches. */}
      {selectedNode ? null : (
        <View className="absolute bottom-3 left-3 right-3">
          <View className="flex-row items-center rounded-sm border border-border bg-card/90 px-3">
            <Text className="mr-2 font-pixel text-sm text-faint-foreground">⌕</Text>
            <TextInput
              testID="graph-search"
              value={query}
              onChangeText={setQuery}
              placeholder="Search files and symbols…"
              placeholderTextColor={colors.faintForeground}
              autoCapitalize="none"
              autoCorrect={false}
              className="min-h-[44px] flex-1 text-sm text-foreground"
            />
            {query.trim() ? (
              <Text
                testID="graph-search-count"
                className="mr-2 font-pixel text-[11px] uppercase text-match"
              >
                {matches.length} {matches.length === 1 ? "match" : "matches"}
              </Text>
            ) : null}
            {query ? (
              <Pressable
                testID="graph-search-clear"
                accessibilityRole="button"
                accessibilityLabel="Clear the search"
                onPress={() => setQuery("")}
                hitSlop={8}
                className="px-1"
              >
                <Text className="font-pixel text-sm text-muted-foreground">✕</Text>
              </Pressable>
            ) : null}
          </View>
        </View>
      )}

      <GraphInspector
        node={selectedNode}
        level={level}
        githubUrl={repo?.github_url ?? ""}
        branch={repo?.ingested_branch ?? null}
        commitSha={repo?.ingested_commit_sha ?? null}
        annotation={selectedAnnotation}
        tourPosition={selectedTourPosition}
        importers={neighbours.importers}
        imports={neighbours.imports}
        onSelectNode={(nodeId) => {
          setPlaying(false);
          setSelectedId(nodeId);
          rendererRef.current?.focusNode(nodeId);
        }}
        onAsk={() => {
          if (!selectedNode || !repo) return;
          const question = `What does ${selectedNode.path} do, and what depends on it?`;
          router.push(
            `/(app)/repo/${repo.repo_number}/chat?q=${encodeURIComponent(question)}` as Href,
          );
        }}
        onOpenExplorer={() => {
          if (!selectedNode || !repo) return;
          router.push(
            `/(app)/repo/${repo.repo_number}/explorer?file=${encodeURIComponent(selectedNode.path)}` as Href,
          );
        }}
        onClose={() => {
          setPlaying(false);
          setSelectedId(null);
          setTourIndex(null);
        }}
      />
    </View>
  );
}
