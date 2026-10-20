/**
 * The repository overview body.
 *
 * @module RepoDetail
 *
 * Port of ``client/src/app/repo/[id]/page.tsx`` (the 341-line web
 * repository page) to a vertical scroll. The web page is a two-column
 * split -- overview on the left, chat on the right -- and the chat half
 * belongs to a later phase, so what is left is a single scrolling column
 * of cards.
 *
 * The cards the web page shows, in the same order and with the same
 * headings:
 *
 * 1. The repository itself -- its GitHub link, branch and commit.
 * 2. The processing status.
 * 3. The AI architecture overview.
 * 4. The detected tech stack.
 *
 * The card surfaces are transparent: the page background shows through and
 * only the border separates a card from the one below it.
 */

import { Linking, Pressable, ScrollView, Text, View } from "react-native";

import type Repository from "@/types/repository";
import type { default as Guide } from "@/types/guide";
import { timeAgo } from "@/lib/timeAgo";
import { formatRepoLabel } from "@/lib/githubUrl";
import { MarkdownText } from "@/ui/MarkdownText";
import { colors } from "@/theme/tokens";

/** Props for the {@link RepoDetail} component. */
export interface RepoDetailProps {
  /** The repository being described. */
  repo: Repository;
  /** The onboarding guide, when it has been generated. */
  guide?: Guide | null;
  /** Test hook. */
  testID?: string;
}

/**
 * One labelled group of the tech stack card.
 */
function StackGroup({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: string;
}) {
  return (
    <View className="mb-3">
      <Text className="mb-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
        {title}
      </Text>
      {items.length > 0 ? (
        <View className="flex-row flex-wrap gap-1.5">
          {items.map((item, index) => (
            <View
              key={`${item}-${index}`}
              className="rounded border px-2 py-0.5"
              style={{
                borderColor: `${tone}33`,
                backgroundColor: `${tone}1a`,
              }}
            >
              <Text className="font-mono text-[10px]" style={{ color: tone }}>
                {item}
              </Text>
            </View>
          ))}
        </View>
      ) : (
        <Text className="text-xs italic text-muted-foreground opacity-50">
          None detected
        </Text>
      )}
    </View>
  );
}

/**
 * Render the repository overview.
 *
 * @param props - The repository and the optional guide.
 * @returns The rendered overview.
 */
export function RepoDetail({
  repo,
  guide,
  testID = "repo-detail",
}: RepoDetailProps) {
  const label = formatRepoLabel(repo.github_url, repo.name);
  const shortSha = repo.ingested_commit_sha
    ? repo.ingested_commit_sha.substring(0, 7)
    : null;

  const stack = repo.detected_stack ?? {
    ci_cd: [],
    databases: [],
    languages: [],
    frameworks: [],
    infrastructure: [],
  };

  const externalIntegrations = (
    guide?.architecture_brief?.external_integrations ?? []
  ).map((tool) => tool.charAt(0).toUpperCase() + tool.slice(1));

  return (
    <ScrollView
      testID={testID}
      className="flex-1 bg-background"
      contentContainerClassName="p-4"
    >
      {/* 1. The repository itself. */}
      <View className="mb-4 rounded border border-border p-4">
        <View className="mb-3 flex-row items-start justify-between">
          <Text className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Repository
          </Text>
          {repo.ingested_branch ? (
            <View className="flex-row items-center rounded border border-primary/20 bg-primary/10 px-2 py-0.5">
              <Text className="mr-1 text-[11px]">🔀</Text>
              <Text className="font-mono text-[10px] text-primary">
                {repo.ingested_branch}
              </Text>
              {shortSha ? (
                <Text className="font-mono text-[10px] text-primary opacity-75">
                  @{shortSha}
                </Text>
              ) : null}
            </View>
          ) : null}
        </View>

        <Pressable
          accessibilityRole="link"
          accessibilityLabel={`Open ${label} on GitHub`}
          onPress={() => void Linking.openURL(repo.github_url)}
          className="flex-row items-center"
        >
          <Text className="mr-2 text-lg text-primary">◈</Text>
          <Text
            className="flex-1 text-xl font-bold text-foreground"
            numberOfLines={2}
          >
            {label}
          </Text>
        </Pressable>
      </View>

      {/* 2. The processing status. */}
      <View className="mb-4 rounded border border-border p-4">
        <Text className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Processing Status
        </Text>
        <View className="flex-row items-end justify-between">
          <Text
            testID="repo-detail-status"
            className="text-xl font-bold uppercase text-success"
          >
            ✓ {repo.status}
          </Text>
          <View className="items-end">
            <Text className="text-[11px] text-muted-foreground">
              Updated: {timeAgo(repo.updated_at)}
            </Text>
            <Text className="text-[11px] text-muted-foreground opacity-60">
              Created: {timeAgo(repo.created_at)}
            </Text>
          </View>
        </View>
      </View>

      {/* 3. The AI architecture overview. */}
      <View className="mb-4 rounded border border-border p-4">
        <Text className="mb-3 text-base font-bold text-foreground">
          AI Architecture Overview
        </Text>
        {repo.architecture_summary ? (
          <MarkdownText
            source={repo.architecture_summary}
            className="text-[13px] leading-[19px] text-muted-foreground"
          />
        ) : (
          <View className="items-center justify-center py-4">
            <Text className="text-[13px] italic text-muted-foreground">
              No architecture summary generated.
            </Text>
          </View>
        )}
      </View>

      {/* 4. The detected tech stack. */}
      <View className="mb-4 rounded border border-border p-4">
        <Text className="mb-3 text-base font-bold text-foreground">
          Tech Stack Detected
        </Text>

        <StackGroup
          title="Languages"
          items={stack.languages ?? []}
          tone={colors.destructive}
        />
        <StackGroup
          title="Frameworks"
          items={stack.frameworks ?? []}
          tone={colors.chart1}
        />
        <StackGroup
          title="Databases"
          items={stack.databases ?? []}
          tone={colors.chart1}
        />
        <StackGroup
          title="Infrastructure"
          items={stack.infrastructure ?? []}
          tone={colors.chart1}
        />
        <StackGroup
          title="CI/CD And Infra"
          items={stack.ci_cd ?? []}
          tone={colors.chart1}
        />
        <StackGroup
          title="External"
          items={externalIntegrations}
          tone={colors.chart1}
        />
      </View>
    </ScrollView>
  );
}

export default RepoDetail;
