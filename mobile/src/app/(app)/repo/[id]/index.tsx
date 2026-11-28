/**
 * The repository overview screen.
 *
 * @module RepoIndexScreen
 *
 * The "Home" tab of the repository shell. It branches on the repository's
 * status the same way the web repository page does:
 *
 * - ``ready`` -- the overview cards: brief, graph, stats, reading order,
 *   riskiest files, activity, stack and owners.
 * - anything else -- the live ingest view, which watches the pipeline run
 *   and keeps the raw log one tap away.
 *
 * The guide request is gated on the repository being ready, so a
 * repository still being indexed spends no requests on an endpoint that
 * would answer 404.
 */

import { useEffect, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";
import { useGlobalSearchParams } from "expo-router";

import { useRepository } from "@/hooks/useRepositories";
import { useQuery } from "@tanstack/react-query";

import { getGraph } from "@/api/graph";
import { queryKeys } from "@/api/queryKeys";
import {
  useRepositoryActivity,
  useRepositoryGuide,
  useRepositoryStats,
} from "@/hooks/useRepoGuide";
import { isReadyStatus } from "@/lib/repoStatus";
import { IngestFlow } from "@/components/IngestFlow";
import { RepoDetail } from "@/ui/RepoDetail";
import { colors } from "@/theme/tokens";

/**
 * Render the repository overview.
 *
 * @returns The overview, the not-ready view, or a loading placeholder.
 */
export default function RepoIndexScreen() {
  // ``useGlobalSearchParams``, not the local variant: these screens are
  // tab children, not the ``[id]`` segment itself, and a local lookup
  // only sees the current route's own params -- which is why every
  // screen here used to receive an empty id and render nothing.
  const { id } = useGlobalSearchParams<{ id: string }>();
  const repoNumber = String(id ?? "");

  const { data: repo, isLoading, isError } = useRepository(repoNumber);

  const ready = isReadyStatus(repo?.status);
  const { data: guide } = useRepositoryGuide(repo?.id, ready);
  const { data: stats } = useRepositoryStats(repo?.id, ready);
  const { data: activity } = useRepositoryActivity(repo?.id, ready);
  // The same query key as the graph screen, so opening the graph after the
  // overview reuses this payload instead of fetching it again.
  const { data: graph } = useQuery({
    queryKey: queryKeys.repositories.graph(repo?.id ?? "", "file"),
    queryFn: () => getGraph(repo?.id as string, "file"),
    enabled: ready && Boolean(repo?.id),
  });

  // When the repository fails, the pipeline retries for a short while
  // before the failure is final. The web client draws that distinction
  // with two different headlines; this remembers when the failure was
  // first seen so the same copy can be chosen.
  const [failedSince, setFailedSince] = useState<number | null>(null);
  useEffect(() => {
    if (repo?.status === "failed") {
      setFailedSince((previous) => previous ?? Date.now());
    } else {
      setFailedSince(null);
    }
  }, [repo?.status]);

  if (isError) {
    return (
      <View className="flex-1 items-center justify-center bg-background p-6">
        <Text className="text-[13px] text-muted-foreground">
          This repository could not be loaded.
        </Text>
      </View>
    );
  }

  if (isLoading || !repo) {
    return (
      <View className="flex-1 items-center justify-center bg-background">
        <ActivityIndicator size="large" color={colors.foreground} />
      </View>
    );
  }

  if (!ready) {
    const failureAgeMs =
      repo.status === "failed"
        ? failedSince === null
          ? 0
          : Date.now() - failedSince
        : undefined;

    return (
      <IngestFlow
        repoId={repo.id}
        repoNumber={repoNumber}
        status={repo.status}
        failureAgeMs={failureAgeMs}
      />
    );
  }

  return <RepoDetail repo={repo} guide={guide} stats={stats} activity={activity} graph={graph} />;
}
