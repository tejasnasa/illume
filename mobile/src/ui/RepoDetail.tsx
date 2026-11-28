/**
 * The repository overview body.
 *
 * @module RepoDetail
 *
 * Port of ``client/src/app/repo/[id]/page.tsx``. The web page is a bento
 * grid; on a phone the same cards stack in one column in the same order:
 * identity and risk spread, the architecture brief, a graph tile, the
 * repository at a glance, where to start reading, the riskiest files,
 * recent activity, the tech stack and who to ask. The chat is a screen of
 * its own on a phone, reached from the button under the header.
 *
 * Each card is left out when its data is missing, so a repository whose
 * stats, guide or graph failed to load shows what it has.
 */

import { Linking, Pressable, ScrollView, Text, View } from "react-native";
import { router, type Href } from "expo-router";

import {
  ActivityCard,
  BriefCard,
  GlanceCard,
  GraphTile,
  PeopleCard,
  RiskCard,
  RiskSpread,
  StackCard,
  StartHereCard,
} from "@/components/overview/OverviewCards";
import { formatRepoLabel } from "@/lib/githubUrl";
import { statusTone } from "@/lib/repoStatus";
import { PEOPLE_ROWS, RISK_ROWS, START_STEPS } from "@/lib/overview";
import { timeAgo } from "@/lib/timeAgo";
import { colors } from "@/theme/tokens";
import type Graph from "@/types/graph";
import type { default as Guide, ActivityItem, Stats } from "@/types/guide";
import type Repository from "@/types/repository";

/** Props for the {@link RepoDetail} component. */
export interface RepoDetailProps {
  /** The repository being described. */
  repo: Repository;
  /** The onboarding guide, when it has been generated. */
  guide?: Guide | null;
  /** Aggregated stats, when they have loaded. */
  stats?: Stats | null;
  /** Recent pull requests and commits, when they have loaded. */
  activity?: readonly ActivityItem[] | null;
  /** The file graph, when it has loaded. */
  graph?: Graph | null;
  /** Test hook. */
  testID?: string;
}

/**
 * Render the repository overview.
 *
 * @param props - The repository and whatever supporting data has loaded.
 * @returns The rendered overview.
 */
export function RepoDetail({
  repo,
  guide,
  stats,
  activity,
  graph,
  testID = "repo-detail",
}: RepoDetailProps) {
  const label = formatRepoLabel(repo.github_url, repo.name);
  const shortSha = repo.ingested_commit_sha ? repo.ingested_commit_sha.substring(0, 7) : null;
  const tone = statusTone(repo.status);
  const toneColor =
    tone === "destructive" ? colors.destructive : tone === "success" ? colors.chart2 : colors.warning;

  const base = `/(app)/repo/${repo.repo_number}`;
  const go = (path: string) => router.push(`${base}/${path}` as Href);
  const openFile = (file: string) => go(`explorer?file=${encodeURIComponent(file)}`);

  const external = (guide?.architecture_brief?.external_integrations ?? []).map(
    (tool) => tool.charAt(0).toUpperCase() + tool.slice(1),
  );
  const steps = guide?.reading_order ?? [];
  const risky = guide?.critical_files ?? [];
  const people = stats?.top_contributors ?? [];
  const recent = activity ?? [];

  return (
    <ScrollView
      testID={testID}
      className="flex-1"
      contentContainerClassName="p-4 pb-10"
    >
      <View className="mb-4 gap-3">
        <View className="flex-row flex-wrap items-center gap-2">
          <View
            className="flex-row items-center gap-1.5 border px-2 py-1"
            style={{ borderColor: `${toneColor}55` }}
          >
            <View style={{ width: 6, height: 6, backgroundColor: toneColor }} />
            <Text
              testID="repo-detail-status"
              className="font-pixel text-xs uppercase"
              style={{ color: toneColor }}
            >
              {repo.status}
            </Text>
          </View>
          {repo.ingested_branch ? (
            <View className="flex-row items-center gap-1 border border-border px-2 py-1">
              <Text className="font-pixel text-xs text-muted-foreground">⎇</Text>
              <Text className="font-pixel text-xs text-muted-foreground">
                {repo.ingested_branch}
              </Text>
              {shortSha ? (
                <Text className="font-pixel text-xs text-accent">@{shortSha}</Text>
              ) : null}
            </View>
          ) : null}
          <Text className="font-pixel text-xs text-faint-foreground">
            Updated {timeAgo(repo.updated_at)}
          </Text>
        </View>

        <Text
          testID="repo-detail-title"
          className="font-pixel text-[34px] leading-[38px] text-foreground"
          numberOfLines={3}
        >
          {label}
        </Text>

        <Pressable
          accessibilityRole="link"
          accessibilityLabel={`Open ${label} on GitHub`}
          onPress={() => void Linking.openURL(repo.github_url)}
          className="min-h-[44px] justify-center"
        >
          <Text className="font-pixel text-[13px] text-muted-foreground">
            github.com/{label} ↗
          </Text>
        </Pressable>
      </View>

      {graph && graph.nodes.length > 0 ? (
        <RiskSpread graph={graph} onOpen={() => go("graph")} />
      ) : null}

      <Pressable
        testID="repo-detail-chat"
        accessibilityRole="button"
        accessibilityLabel="Ask a question about this repository"
        onPress={() => go("chat")}
        className="mb-4 min-h-[44px] flex-row items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5"
      >
        <Text className="font-pixel text-[13px] text-primary-foreground">Ask about this code</Text>
      </Pressable>

      <BriefCard summary={repo.architecture_summary} onGlossary={() => go("glossary")} />

      {graph && graph.nodes.length > 0 ? (
        <GraphTile repoId={repo.id} graph={graph} onOpen={() => go("graph")} />
      ) : null}

      {stats ? <GlanceCard stats={stats} /> : null}

      {steps.length > 0 ? (
        <StartHereCard
          steps={steps.slice(0, START_STEPS)}
          onOpenFile={openFile}
          onTour={() => go("graph")}
        />
      ) : null}

      {risky.length > 0 ? (
        <RiskCard
          files={risky.slice(0, RISK_ROWS)}
          onOpenExplorer={() => go("explorer")}
          onOpenFile={openFile}
        />
      ) : null}

      {recent.length > 0 ? <ActivityCard items={recent} githubUrl={repo.github_url} /> : null}

      <StackCard stack={repo.detected_stack} external={external} />

      {people.length > 0 ? <PeopleCard people={people.slice(0, PEOPLE_ROWS)} /> : null}
    </ScrollView>
  );
}

export default RepoDetail;
