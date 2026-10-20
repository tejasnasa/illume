/**
 * The repository overview screen.
 *
 * @module RepoIndexScreen
 *
 * The "Home" tab of the repository shell. It branches on the repository's
 * status the same way the web repository page does:
 *
 * - ``ready`` -- the overview: identity, status, architecture summary and
 *   the detected tech stack.
 * - anything else -- the not-ready view, which names the pipeline stage
 *   the repository is at.
 *
 * The guide request is gated on the repository being ready, so a
 * repository still being indexed spends no requests on an endpoint that
 * would answer 404.
 */

import { useEffect, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";
import { useLocalSearchParams } from "expo-router";

import { useRepository } from "@/hooks/useRepositories";
import { useRepositoryGuide } from "@/hooks/useRepoGuide";
import { isReadyStatus } from "@/lib/repoStatus";
import { formatRepoLabel } from "@/lib/githubUrl";
import { RepoDetail } from "@/ui/RepoDetail";
import { RepoStatusView } from "@/ui/RepoStatusView";
import { colors } from "@/theme/tokens";

/**
 * Render the repository overview.
 *
 * @returns The overview, the not-ready view, or a loading placeholder.
 */
export default function RepoIndexScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const repoNumber = String(id ?? "");

  const { data: repo, isLoading, isError } = useRepository(repoNumber);

  const ready = isReadyStatus(repo?.status);
  const { data: guide } = useRepositoryGuide(repo?.id, ready);

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
      <RepoStatusView
        status={repo.status}
        failureAgeMs={failureAgeMs}
        repoLabel={formatRepoLabel(repo.github_url, repo.name)}
        branch={repo.ingested_branch}
        commitSha={repo.ingested_commit_sha}
      />
    );
  }

  return <RepoDetail repo={repo} guide={guide} />;
}
