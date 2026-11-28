/**
 * The cards of the repository overview.
 *
 * @module OverviewCards
 *
 * Port of the bento cards in ``client/src/app/repo/[id]/page.tsx`` and of the
 * tiles in ``client/src/components/OverviewGraphTiles.tsx``. The web lays the
 * cards out on a twelve-column grid; on a phone they stack in a single
 * column in the same reading order. Every card is left out when its data is
 * missing, so a repository whose stats failed to load shows what it has
 * rather than empty boxes.
 */

import { useMemo, type ReactNode } from "react";
import { Linking, Pressable, Text, View } from "react-native";

import { AgentMarkdown } from "@/components/chat/AgentMarkdown";
import {
  PEOPLE_COLORS,
  PEOPLE_ROWS,
  RISK_LEVELS,
  RISK_ROWS,
  START_STEPS,
  activityHref,
  activityTag,
  compactNumber,
  initialsOf,
  languageShares,
  percent,
  riskCounts,
  riskOf,
  stripLeadingTitle,
} from "@/lib/overview";
import { timeAgo } from "@/lib/timeAgo";
import { colors } from "@/theme/tokens";
import { Eyebrow, Panel } from "@/ui/Panel";
import { RepoThumb } from "@/ui/RepoThumb";
import type Graph from "@/types/graph";
import type { default as Guide, ActivityItem, Stats } from "@/types/guide";
import type Repository from "@/types/repository";

/** A bordered card with a pixel title row. */
export function Card({
  title,
  action,
  testID,
  children,
}: {
  title: string;
  action?: ReactNode;
  testID?: string;
  children: ReactNode;
}) {
  return (
    <Panel testID={testID} className="mb-4 gap-4 p-4">
      <View className="flex-row items-center justify-between gap-2">
        <Eyebrow>{title}</Eyebrow>
        {action}
      </View>
      {children}
    </Panel>
  );
}

/** A small pixel link in a card's title row. */
export function CardLink({
  label,
  onPress,
  testID,
}: {
  label: string;
  onPress: () => void;
  testID?: string;
}) {
  return (
    <Pressable
      testID={testID}
      accessibilityRole="link"
      accessibilityLabel={label}
      onPress={onPress}
      hitSlop={8}
    >
      <Text className="font-pixel text-xs uppercase tracking-[0.7px] text-muted-foreground">
        {label}
      </Text>
    </Pressable>
  );
}

/** The architecture brief. */
export function BriefCard({
  summary,
  onGlossary,
}: {
  summary: string | null;
  onGlossary: () => void;
}) {
  return (
    <Card
      title="Architecture brief"
      testID="overview-brief"
      action={<CardLink label="Glossary →" onPress={onGlossary} testID="overview-glossary" />}
    >
      {summary ? (
        <AgentMarkdown text={stripLeadingTitle(summary)} />
      ) : (
        <Text className="font-pixel text-xs uppercase text-faint-foreground">
          No architecture summary generated.
        </Text>
      )}
    </Card>
  );
}

/**
 * The graph tile: the same still frame of the repository's graph that its
 * dashboard card shows, and the graph's size.
 */
export function GraphTile({
  repoId,
  graph,
  onOpen,
}: {
  repoId: string;
  graph: Graph;
  onOpen: () => void;
}) {
  return (
    <Pressable
      testID="overview-graph"
      accessibilityRole="button"
      accessibilityLabel="Open the dependency graph"
      onPress={onOpen}
      className="mb-4 overflow-hidden rounded-md border border-border bg-card"
    >
      <View style={{ height: 180, backgroundColor: "#060608" }}>
        <RepoThumb repoId={repoId} height={180} />
        <Text className="absolute left-4 top-3 font-pixel text-xs uppercase tracking-[1.4px] text-muted-foreground">
          Dependency graph
        </Text>
      </View>
      <View className="flex-row items-center justify-between border-t border-border px-4 py-3">
        <Text className="font-pixel text-xs uppercase text-muted-foreground">
          {graph.metadata.total_nodes.toLocaleString("en-US")} files ·{" "}
          {graph.metadata.total_edges.toLocaleString("en-US")} edges
        </Text>
        <Text className="font-pixel text-xs uppercase text-accent">Open 3D →</Text>
      </View>
    </Pressable>
  );
}

/** How many files fall in each risk level, as a bar. */
export function RiskSpread({ graph, onOpen }: { graph: Graph; onOpen: () => void }) {
  const counts = useMemo(() => riskCounts(graph.nodes), [graph]);
  const total = graph.nodes.length;
  return (
    <Pressable
      testID="overview-risk-spread"
      accessibilityRole="button"
      accessibilityLabel={`Risk spread across ${total} files: ${RISK_LEVELS.map(
        (r) => `${counts[r.key]} ${r.label.toLowerCase()}`,
      ).join(", ")}. Open the graph.`}
      onPress={onOpen}
      className="mb-4 gap-2.5 rounded-md border border-border bg-card px-4 py-3.5"
    >
      <View className="flex-row justify-between">
        <Text className="font-pixel text-[11px] uppercase tracking-[1.4px] text-muted-foreground">
          Risk spread · {total.toLocaleString("en-US")} files
        </Text>
        <Text className="font-pixel text-[11px] uppercase text-subtle-foreground">Graph →</Text>
      </View>
      <View className="h-2.5 flex-row gap-0.5">
        {RISK_LEVELS.map((r) =>
          counts[r.key] > 0 ? (
            <View
              key={r.key}
              style={{ flex: counts[r.key], minWidth: 6, backgroundColor: r.color }}
            />
          ) : null,
        )}
      </View>
      <View className="flex-row flex-wrap gap-x-4 gap-y-1.5">
        {RISK_LEVELS.map((r) => (
          <View key={r.key} className="flex-row items-center gap-1.5">
            <View style={{ width: 6, height: 6, backgroundColor: r.color }} />
            <Text className="font-pixel text-xs uppercase text-zinc-300">
              {counts[r.key].toLocaleString("en-US")} {r.label}
            </Text>
          </View>
        ))}
      </View>
    </Pressable>
  );
}

/** One big number over a small label. */
function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <View className="w-1/2 gap-0.5 pb-3 pr-3">
      <Text className="font-pixel text-3xl text-foreground" style={color ? { color } : undefined}>
        {value}
      </Text>
      <Text className="font-pixel text-[11px] uppercase tracking-[1px] text-subtle-foreground">
        {label}
      </Text>
    </View>
  );
}

/** Totals and the language bar. */
export function GlanceCard({ stats }: { stats: Stats }) {
  const shares = useMemo(() => languageShares(stats), [stats]);
  return (
    <Card title="At a glance" testID="overview-glance">
      <View className="flex-row flex-wrap">
        <Stat label="Files" value={compactNumber(stats.total_files)} />
        <Stat label="Lines" value={compactNumber(stats.total_loc)} />
        <Stat label="Contributors" value={compactNumber(stats.total_contributors)} />
        <Stat
          label="Silos"
          value={compactNumber(stats.knowledge_silo_count)}
          color={stats.knowledge_silo_count > 0 ? colors.warning : undefined}
        />
      </View>
      {shares.length > 0 ? (
        <View className="gap-2.5">
          <View
            testID="overview-language-bar"
            accessible
            accessibilityRole="image"
            accessibilityLabel={`Lines by language: ${shares
              .map((s) => `${s.name} ${percent(s.share)}`)
              .join(", ")}`}
            className="h-2.5 flex-row gap-0.5"
          >
            {shares.map((s) => (
              <View key={s.name} style={{ flex: s.loc, minWidth: 4, backgroundColor: s.color }} />
            ))}
          </View>
          <View className="flex-row flex-wrap gap-x-3.5 gap-y-1.5">
            {shares.map((s) => (
              <View key={s.name} className="flex-row items-center gap-1.5">
                <View style={{ width: 6, height: 6, backgroundColor: s.color }} />
                <Text className="font-pixel text-[11px] text-foreground">
                  {s.name} <Text className="text-muted-foreground">{percent(s.share)}</Text>
                </Text>
              </View>
            ))}
          </View>
        </View>
      ) : null}
    </Card>
  );
}

/** The first files of the reading order. */
export function StartHereCard({
  steps,
  onOpenFile,
  onTour,
}: {
  steps: Guide["reading_order"];
  onOpenFile: (path: string) => void;
  onTour: () => void;
}) {
  const shown = steps.slice(0, START_STEPS);
  return (
    <Card
      title="Start here"
      testID="overview-start-here"
      action={<CardLink label="Reading tour →" onPress={onTour} testID="overview-tour" />}
    >
      <View className="gap-0.5">
        {shown.map((step) => (
          <Pressable
            key={step.file_path}
            testID={`overview-step-${step.position}`}
            accessibilityRole="button"
            accessibilityLabel={`Open ${step.file_path}`}
            onPress={() => onOpenFile(step.file_path)}
            className="flex-row items-start gap-3 rounded-sm px-1 py-2 active:bg-secondary"
          >
            <Text
              className={`w-6 font-pixel text-[13px] ${
                step.position === 1 ? "text-accent" : "text-faint-foreground"
              }`}
            >
              {String(step.position).padStart(2, "0")}
            </Text>
            <View className="min-w-0 flex-1 gap-0.5">
              <Text numberOfLines={1} className="font-pixel text-[13px] text-foreground">
                {step.file_path}
              </Text>
              {step.annotation ? (
                <Text numberOfLines={2} className="text-xs text-subtle-foreground">
                  {step.annotation}
                </Text>
              ) : null}
            </View>
          </Pressable>
        ))}
      </View>
    </Card>
  );
}

/** The riskiest files, as bars scaled to the busiest one's fan-in. */
export function RiskCard({
  files,
  onOpenExplorer,
  onOpenFile,
}: {
  files: Guide["critical_files"];
  onOpenExplorer: () => void;
  onOpenFile: (path: string) => void;
}) {
  const shown = files.slice(0, RISK_ROWS);
  const max = Math.max(1, ...shown.map((f) => f.fan_in));
  return (
    <Card
      title="Riskiest to change"
      testID="overview-risk"
      action={<CardLink label="Explorer →" onPress={onOpenExplorer} testID="overview-explorer" />}
    >
      <View className="gap-3">
        {shown.map((f) => {
          const level = riskOf(f.criticality);
          const color = RISK_LEVELS.find((r) => r.key === level)!.color;
          return (
            <Pressable
              key={f.file_path}
              testID={`overview-risk-${f.file_path}`}
              accessibilityRole="button"
              accessibilityLabel={`Open ${f.file_path}`}
              onPress={() => onOpenFile(f.file_path)}
              className="gap-1.5"
            >
              <View className="flex-row justify-between gap-2">
                <Text numberOfLines={1} className="min-w-0 flex-1 font-pixel text-[13px] text-foreground">
                  {f.file_path}
                </Text>
                <Text className="font-pixel text-[11px] uppercase" style={{ color }}>
                  {level}
                </Text>
              </View>
              <View className="h-1.5 bg-secondary">
                <View
                  style={{
                    height: 6,
                    width: `${Math.max(4, (f.fan_in / max) * 100)}%`,
                    backgroundColor: color,
                  }}
                />
              </View>
              <Text className="font-pixel text-[11px] uppercase text-faint-foreground">
                Fan-in {f.fan_in}
                {f.change_frequency > 0 ? ` · ${f.change_frequency} changes` : ""}
                {f.has_tests ? "" : " · no tests"}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </Card>
  );
}

/** Latest merged pull requests and commits. */
export function ActivityCard({
  items,
  githubUrl,
}: {
  items: readonly ActivityItem[];
  githubUrl: string;
}) {
  return (
    <Card
      title="Recent activity"
      testID="overview-activity"
      action={
        <CardLink label="GitHub ↗" onPress={() => void Linking.openURL(githubUrl)} />
      }
    >
      <View className="gap-0.5">
        {items.map((item) => {
          const href = activityHref(githubUrl, item);
          const isPr = item.kind === "pull_request";
          const meta = [item.author, timeAgo(item.at)].filter(Boolean).join(" · ");
          return (
            <Pressable
              key={`${item.kind}-${item.number ?? item.hash}`}
              testID="overview-activity-row"
              accessibilityRole={href ? "link" : "text"}
              accessibilityLabel={item.title}
              disabled={!href}
              onPress={() => href && void Linking.openURL(href)}
              className="flex-row items-start gap-3 rounded-sm px-1 py-2 active:bg-secondary"
            >
              <Text
                className={`w-14 font-pixel text-xs ${isPr ? "text-accent" : "text-chart-1"}`}
              >
                {activityTag(item)}
              </Text>
              <View className="min-w-0 flex-1 gap-0.5">
                <Text numberOfLines={1} className="text-[13px] text-foreground">
                  {item.title}
                </Text>
                <Text className="font-pixel text-[11px] text-subtle-foreground">{meta}</Text>
              </View>
            </Pressable>
          );
        })}
      </View>
    </Card>
  );
}

/** One labelled row of the tech stack. */
function StackRow({
  label,
  items,
  tone,
}: {
  label: string;
  items: readonly string[] | null | undefined;
  tone: "neutral" | "accent" | "cyan";
}) {
  if (!items || items.length === 0) return null;
  const border =
    tone === "accent" ? "#f6339a66" : tone === "cyan" ? "#53eafd59" : colors.border;
  const text = tone === "accent" ? colors.accent : tone === "cyan" ? colors.chart1 : "#d4d4d8";
  return (
    <View className="gap-1.5" testID={`stack-${label}`}>
      <Text className="font-pixel text-[11px] uppercase tracking-[1px] text-subtle-foreground">
        {label}
      </Text>
      <View className="flex-row flex-wrap gap-1.5">
        {items.map((tool, i) => (
          <View
            key={`${tool}-${i}`}
            className="rounded-sm border px-2 py-1"
            style={{ borderColor: border }}
          >
            <Text className="font-pixel text-xs" style={{ color: text }}>
              {tool}
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}

/** The detected tech stack plus the brief's external integrations. */
export function StackCard({
  stack,
  external,
}: {
  stack: Repository["detected_stack"] | null | undefined;
  external: readonly string[];
}) {
  const groups = [
    stack?.languages,
    stack?.frameworks,
    stack?.databases,
    stack?.infrastructure,
    stack?.ci_cd,
    external,
  ];
  if (!groups.some((g) => g && g.length > 0)) return null;
  return (
    <Card title="Tech stack" testID="overview-stack">
      <View className="gap-3.5">
        <StackRow label="Languages" items={stack?.languages} tone="accent" />
        <StackRow label="Frameworks" items={stack?.frameworks} tone="cyan" />
        <StackRow label="Databases" items={stack?.databases} tone="neutral" />
        <StackRow label="Infra" items={stack?.infrastructure} tone="neutral" />
        <StackRow label="CI / CD" items={stack?.ci_cd} tone="neutral" />
        <StackRow label="External" items={external} tone="neutral" />
      </View>
    </Card>
  );
}

/** The people who own the most files. */
export function PeopleCard({ people }: { people: Stats["top_contributors"] }) {
  return (
    <Card
      title="Who to ask"
      testID="overview-people"
      action={
        <Text className="font-pixel text-xs uppercase text-faint-foreground">From git history</Text>
      }
    >
      <View className="gap-3">
        {people.slice(0, PEOPLE_ROWS).map((p, i) => (
          <View key={p.name} className="flex-row items-center gap-3.5">
            <View
              accessibilityElementsHidden
              importantForAccessibility="no-hide-descendants"
              className="h-9 w-9 items-center justify-center"
              style={{ backgroundColor: PEOPLE_COLORS[i % PEOPLE_COLORS.length] }}
            >
              <Text className="font-pixel text-[13px] text-foreground">{initialsOf(p.name)}</Text>
            </View>
            <Text numberOfLines={1} className="min-w-0 flex-1 text-sm text-foreground">
              {p.name}
            </Text>
            <Text className="font-pixel text-xs text-muted-foreground">{p.files_owned} files</Text>
          </View>
        ))}
      </View>
    </Card>
  );
}
