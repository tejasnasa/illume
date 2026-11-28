/**
 * Repository card for the dashboard, in every ingestion state.
 *
 * @module RepoCard
 *
 * Port of ``client/src/components/ui/RepoCard.tsx``. A picture of the
 * repository's own graph on top with the status and primary language laid
 * over it, then the owner and name in the pixel font, the branch and short
 * commit it was read at, a body that depends on the state (progress while
 * ingesting, a notice when failed, the architecture summary when ready),
 * the detected stack, and a footer with the auto-update state and the time
 * of the last change.
 *
 * The whole card is one ``Pressable``; the parent decides what ``onPress``
 * does (the dashboard navigates to the repository shell).
 */

import { useMemo } from "react";
import { Pressable, Text, View } from "react-native";

import { PIXEL_FONT } from "@/lib/fonts";
import { splitRepoName } from "@/lib/repoName";
import { statusView, syncView } from "@/lib/repoStatus";
import { timeAgo } from "@/lib/timeAgo";
import { colors } from "@/theme/tokens";
import { Blink } from "@/ui/Blink";
import { RepoThumb } from "@/ui/RepoThumb";
import type Repository from "@/types/repository";

export interface RepoCardProps {
  /** The repository record rendered by this card. */
  repo: Repository;
  /** Stable per-row press handler; the dashboard owns navigation. */
  onPress?: (repo: Repository) => void;
}

/** The coarse statuses an ingest moves through, in order. */
const INGEST_STEPS = ["pending", "cloning", "parsing", "embedding"] as const;

/** What each step is doing, in words. */
const STEP_LABEL: Record<string, string> = {
  pending: "Queued",
  cloning: "Fetching the repository",
  parsing: "Parsing and mapping files",
  embedding: "Writing the guide",
};

/** The most stack labels a card shows. */
const MAX_STACK = 4;

/** A square status dot that pulses while the thing it describes is live. */
function Dot({ color, live }: { color: string; live: boolean }) {
  return (
    <Blink active={live}>
      <View style={{ width: 6, height: 6, backgroundColor: color }} />
    </Blink>
  );
}

/**
 * Render a tap-target summarising one repository.
 *
 * @param props - The repository and the press handler.
 * @returns The card.
 */
export function RepoCard({ repo, onPress }: RepoCardProps) {
  const view = statusView(repo.status);
  const sync = syncView(repo);
  const { owner, name } = splitRepoName(repo.github_url, repo.name);

  const stack = useMemo<string[]>(
    () =>
      [
        ...new Set([
          ...(repo.detected_stack?.languages ?? []),
          ...(repo.detected_stack?.frameworks ?? []),
        ]),
      ].slice(0, MAX_STACK),
    [repo.detected_stack],
  );

  const shortSha = repo.ingested_commit_sha?.slice(0, 7) ?? null;
  const stepIndex = Math.max(0, INGEST_STEPS.indexOf(repo.status as never));

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Open ${repo.name}`}
      onPress={onPress ? () => onPress(repo) : undefined}
      className="mb-3 overflow-hidden rounded-sm border border-border bg-card active:border-border-strong"
    >
      <View className="border-b border-border bg-[#060608]">
        <RepoThumb
          repoId={repo.id}
          tone={view.kind === "ready" ? "ready" : "muted"}
        />
        <View
          testID="repo-card-status"
          className="absolute left-3 top-2.5 flex-row items-center gap-1.5 border bg-background/80 px-2 py-1"
          style={{ borderColor: `${view.color}66` }}
        >
          <Dot color={view.color} live={view.kind === "ingesting"} />
          <Text
            className="text-[11px] uppercase tracking-[1px]"
            style={{ fontFamily: PIXEL_FONT, color: view.color }}
          >
            {view.label}
          </Text>
        </View>
        {repo.primary_language ? (
          <Text
            className="absolute right-3 top-2.5 text-[11px] uppercase tracking-[1px] text-subtle-foreground"
            style={{ fontFamily: PIXEL_FONT }}
          >
            {repo.primary_language}
          </Text>
        ) : null}
      </View>

      <View className="gap-3 p-4">
        <View className="flex-row items-start justify-between gap-2.5">
          <View className="min-w-0 flex-1 gap-1.5">
            <Text
              numberOfLines={1}
              className="text-xl leading-tight text-foreground"
              style={{ fontFamily: PIXEL_FONT }}
            >
              {owner ? (
                <Text className="text-subtle-foreground">{owner}/</Text>
              ) : null}
              <Text>{name}</Text>
            </Text>
            {repo.ingested_branch || shortSha ? (
              <Text
                numberOfLines={1}
                className="text-xs text-muted-foreground"
                style={{ fontFamily: PIXEL_FONT }}
              >
                {"⎇ "}
                {repo.ingested_branch ?? "detached"}
                {shortSha ? (
                  <>
                    <Text className="text-faint-foreground">{" @ "}</Text>
                    <Text className="text-accent">{shortSha}</Text>
                  </>
                ) : null}
              </Text>
            ) : null}
          </View>
          <Text
            accessibilityElementsHidden
            importantForAccessibility="no"
            className="text-lg text-faint-foreground"
            style={{ fontFamily: PIXEL_FONT }}
          >
            →
          </Text>
        </View>

        {view.kind === "ingesting" ? (
          <View
            testID="repo-card-progress"
            className="gap-2 rounded-sm border border-dashed border-border-strong p-3"
          >
            <View className="flex-row justify-between">
              <Text
                className="text-xs text-zinc-300"
                style={{ fontFamily: PIXEL_FONT }}
              >
                {STEP_LABEL[repo.status] ?? "Working"}
              </Text>
              <Text
                className="text-xs text-accent"
                style={{ fontFamily: PIXEL_FONT }}
              >
                {stepIndex + 1}/{INGEST_STEPS.length}
              </Text>
            </View>
            <View className="flex-row gap-0.5" accessibilityElementsHidden>
              {INGEST_STEPS.map((step, i) => (
                <Blink key={step} active={i === stepIndex} style={{ flex: 1 }}>
                  <View
                    style={{
                      height: 6,
                      backgroundColor:
                        i < stepIndex
                          ? colors.chart2
                          : i === stepIndex
                            ? colors.accent
                            : colors.muted,
                    }}
                  />
                </Blink>
              ))}
            </View>
            <Text
              className="text-[11px] uppercase tracking-[1px] text-subtle-foreground"
              style={{ fontFamily: PIXEL_FONT }}
            >
              {`Step ${stepIndex + 1} of ${INGEST_STEPS.length} · You can leave this page`}
            </Text>
          </View>
        ) : null}

        {view.kind === "failed" ? (
          <View
            testID="repo-card-failed"
            className="rounded-sm border border-red-500/25 bg-red-500/5 p-3"
          >
            <Text className="text-[13px] leading-[19px] text-red-300">
              This ingest did not finish. Open it to see where it stopped, or
              start it again.
            </Text>
          </View>
        ) : null}

        {view.kind === "ready" ? (
          repo.architecture_summary ? (
            <Text
              numberOfLines={3}
              className="text-sm leading-[21px] text-zinc-400"
            >
              {repo.architecture_summary}
            </Text>
          ) : (
            <Text
              className="text-xs uppercase text-faint-foreground"
              style={{ fontFamily: PIXEL_FONT }}
            >
              No summary yet
            </Text>
          )
        ) : null}

        {stack.length > 0 ? (
          <View className="flex-row flex-wrap gap-1.5">
            {stack.map((item) => (
              <View
                key={item}
                className="rounded-[3px] border border-border px-2 py-1"
              >
                <Text
                  className="text-[11px] text-zinc-300"
                  style={{ fontFamily: PIXEL_FONT }}
                >
                  {item}
                </Text>
              </View>
            ))}
          </View>
        ) : null}

        <View className="flex-row justify-between gap-2.5 border-t border-border pt-3">
          <View className="flex-row items-center gap-1.5">
            <Dot color={sync.color} live={sync.live} />
            <Text
              className="text-[11px] uppercase tracking-[1px] text-subtle-foreground"
              style={{ fontFamily: PIXEL_FONT }}
            >
              {sync.label}
            </Text>
          </View>
          <Text
            className="text-[11px] uppercase tracking-[1px] text-subtle-foreground"
            style={{ fontFamily: PIXEL_FONT }}
          >
            {timeAgo(repo.updated_at)}
          </Text>
        </View>
      </View>
    </Pressable>
  );
}
