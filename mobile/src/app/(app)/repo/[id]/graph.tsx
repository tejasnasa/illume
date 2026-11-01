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
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { useGlobalSearchParams } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { getGraph, type GraphLevel } from "@/api/graph";
import { queryKeys } from "@/api/queryKeys";
import { GraphInspector } from "@/components/GraphInspector";
import {
  GraphRenderer,
  type GraphRendererHandle,
} from "@/components/GraphRenderer";
import { useRepository } from "@/hooks/useRepositories";
import { useRepositoryGuide } from "@/hooks/useRepoGuide";
import { computeLayout, type LayoutResult } from "@/lib/graphLayout";
import { guideSteps, matchNodes } from "@/lib/graphSelection";
import { isReadyStatus } from "@/lib/repoStatus";
import { colors } from "@/theme/tokens";

/** The levels the graph can be drawn at. */
const LEVELS: readonly { value: GraphLevel; label: string }[] = [
  { value: "file", label: "File" },
  { value: "symbol", label: "Symbol" },
];

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
  const insets = useSafeAreaInsets();

  const { data: repo } = useRepository(repoNumber);
  const { data: guide } = useRepositoryGuide(
    repo?.id,
    isReadyStatus(repo?.status),
  );

  const [level, setLevel] = useState<GraphLevel>("file");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tourIndex, setTourIndex] = useState<number | null>(null);
  const [layout, setLayout] = useState<LayoutResult | null>(null);
  const [layoutProgress, setLayoutProgress] = useState(0);

  const rendererRef = useRef<GraphRendererHandle>(null);

  const {
    data: graph,
    isLoading,
    isError,
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
    setLayout(null);
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
    }).then((result) => {
      if (!cancelled) setLayout(result);
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

  if (isError) {
    return (
      <View className="flex-1 items-center justify-center bg-background p-6">
        <Text className="text-[13px] text-muted-foreground">
          The graph could not be loaded.
        </Text>
      </View>
    );
  }

  const busy = isLoading || (Boolean(graph) && !layout);

  return (
    <View className="flex-1 bg-background">
      {layout ? (
        <GraphRenderer
          ref={rendererRef}
          positions={layout.positions}
          links={layout.links}
          nodes={graph?.nodes ?? []}
          boundingRadius={layout.boundingRadius}
          selectedNodeId={selectedId}
          matchNodeIds={matchIds}
          onSelect={(nodeId) => {
            setSelectedId(nodeId);
            if (nodeId === null) setTourIndex(null);
          }}
        />
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
        The level switch, with the legend to its right and the tour under it.
        No safe-area inset here: the repository shell has already applied the
        top inset above the tab bar, and adding it again is what left a gap
        the height of the status bar between the tabs and this row.
      */}
      <View className="absolute left-3 right-3 top-2">
        <View className="flex-row items-start justify-between">
          <View className="flex-row rounded border border-border bg-background/90">
            {LEVELS.map((entry) => {
              const active = level === entry.value;
              return (
                <Pressable
                  key={entry.value}
                  testID={`graph-level-${entry.value}`}
                  accessibilityRole="button"
                  accessibilityState={{ selected: active }}
                  accessibilityLabel={`${entry.label} level`}
                  onPress={() => setLevel(entry.value)}
                  className={`min-h-[40px] justify-center rounded px-4 ${
                    active ? "bg-primary" : "bg-transparent"
                  }`}
                >
                  <Text
                    className={`text-xs font-semibold ${
                      active ? "text-primary-foreground" : "text-muted-foreground"
                    }`}
                  >
                    {entry.label}
                  </Text>
                </Pressable>
              );
            })}
          </View>

          {/* The legend, on the opposite corner from the switch. */}
          <View className="rounded border border-border bg-background/90 px-3 py-2">
            {(
              [
                ["#ef4444", "Critical"],
                ["#facc15", "Caution"],
                ["#22c55e", "Safe"],
              ] as const
            ).map(([colour, label]) => (
              <View key={label} className="flex-row items-center gap-2 py-0.5">
                <View
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 4,
                    backgroundColor: colour,
                  }}
                />
                <Text className="text-[10px] text-muted-foreground">
                  {label}
                </Text>
              </View>
            ))}
            {query.trim() ? (
              <View className="flex-row items-center gap-2 py-0.5">
                <View
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 4,
                    backgroundColor: "#a855f7",
                  }}
                />
                <Text className="text-[10px] text-muted-foreground">
                  Match ({matches.length})
                </Text>
              </View>
            ) : null}
          </View>
        </View>

        {level === "file" && steps.length > 0 ? (
          <View className="mt-2 flex-row self-start items-center gap-2 rounded border border-border bg-background/90 px-2 py-1.5">
            <Text className="text-[10px] font-semibold uppercase tracking-wider text-foreground">
              Reading order
            </Text>
            <Pressable
              testID="graph-tour-previous"
              accessibilityRole="button"
              accessibilityLabel="Previous step"
              accessibilityState={{
                disabled: tourIndex === null || tourIndex === 0,
              }}
              onPress={() => goToStep((tourIndex ?? 0) - 1)}
              disabled={tourIndex === null || tourIndex === 0}
              className="min-h-[36px] min-w-[36px] items-center justify-center rounded border border-border px-2 active:bg-secondary disabled:opacity-30"
            >
              <Text className="text-sm text-foreground">‹</Text>
            </Pressable>
            <Text className="font-mono text-xs text-muted-foreground">
              {tourIndex === null ? "—" : tourIndex + 1} / {steps.length}
            </Text>
            <Pressable
              testID="graph-tour-next"
              accessibilityRole="button"
              accessibilityLabel="Next step"
              accessibilityState={{
                disabled: tourIndex !== null && tourIndex === steps.length - 1,
              }}
              onPress={() => goToStep((tourIndex ?? -1) + 1)}
              disabled={tourIndex !== null && tourIndex === steps.length - 1}
              className="min-h-[36px] min-w-[36px] items-center justify-center rounded border border-border px-2 active:bg-secondary disabled:opacity-30"
            >
              <Text className="text-sm text-foreground">›</Text>
            </Pressable>
          </View>
        ) : null}
      </View>

      {/* The search box. */}
      {selectedNode ? null : (
        <View
          className="absolute left-3 right-3 bottom-3"
          style={{ paddingBottom: insets.bottom }}
        >
          <View className="flex-row items-center rounded border border-border bg-background/90 px-3">
            <Text className="mr-2 text-sm text-muted-foreground">⌕</Text>
            <TextInput
              testID="graph-search"
              value={query}
              onChangeText={setQuery}
              placeholder="Search nodes…"
              placeholderTextColor={colors.mutedForeground}
              autoCapitalize="none"
              autoCorrect={false}
              className="min-h-[44px] flex-1 text-sm text-foreground"
            />
            {query ? (
              <Pressable
                testID="graph-search-clear"
                accessibilityRole="button"
                accessibilityLabel="Clear the search"
                onPress={() => setQuery("")}
                hitSlop={8}
                className="px-1"
              >
                <Text className="text-sm text-muted-foreground">✕</Text>
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
        annotation={selectedAnnotation}
        onClose={() => {
          setSelectedId(null);
          setTourIndex(null);
        }}
      />
    </View>
  );
}
