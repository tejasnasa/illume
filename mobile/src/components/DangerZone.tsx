/**
 * The destructive actions for one repository.
 *
 * @module DangerZone
 *
 * Port of the web client's repository danger zone
 * (``client/src/components/RepoSettings.tsx``). Both actions there sit
 * behind a modal; on a phone the native idiom is ``Alert.alert``, which
 * is the platform's own confirmation sheet and the one a reader already
 * knows how to dismiss.
 *
 * Re-ingest keeps the web's typed confirmation: the reader has to type
 * the repository's name before the button arms, because the action is not
 * merely destructive but *total* -- the endpoint deletes the repository
 * row and recreates it with the same id, which cascades every child row
 * (graph, glossary, reading order, embeddings, chat history) away with
 * it. The confirmation says so.
 *
 * The component owns no navigation: the screen that embeds it decides
 * where the reader goes after a delete or a re-ingest.
 */

import { useCallback, useState } from "react";
import { Alert, Pressable, Text, TextInput, View } from "react-native";

import { GitGraph } from "@/components/GitGraph";
import {
  deleteRepository,
  reingestRepository,
  type ReingestPayload,
  type SettingsRequestOptions,
} from "@/api/settings";
import { parseGitHubRepoUrl } from "@/lib/githubUrl";
import { colors } from "@/theme/tokens";
import type Repository from "@/types/repository";

/**
 * Props for the DangerZone component.
 */
export interface DangerZoneProps {
  /** The repository the actions apply to. */
  repo: Repository;
  /** Transport overrides, so a test can inject a backend and a fetch. */
  options?: SettingsRequestOptions;
  /** Called after the repository was deleted. */
  onDeleted?: () => void;
  /** Called after the re-ingest was queued. */
  onReingested?: () => void;
}

/**
 * The destructive actions for one repository.
 *
 * @param props - The repository, the transport overrides and the callbacks.
 * @returns The rendered danger zone.
 */
export function DangerZone({
  repo,
  options,
  onDeleted,
  onReingested,
}: DangerZoneProps) {
  const [confirmation, setConfirmation] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [versionPickerOpen, setVersionPickerOpen] = useState(false);

  // The git timeline is driven by the GitHub proxy, which needs the
  // repository's owner and name rather than its Id. A repository whose URL
  // is not a GitHub one simply does not offer the version picker.
  const parsed = parseGitHubRepoUrl(repo.github_url);

  // The typed confirmation has to match the repository's name exactly.
  const confirmed = confirmation.trim() === repo.name;

  /**
   * Delete the repository, once the reader has confirmed.
   */
  const handleDelete = useCallback(async () => {
    setError(null);
    setIsBusy(true);
    try {
      await deleteRepository(repo.id, options);
      onDeleted?.();
    } catch (cause) {
      setError(
        cause instanceof Error && cause.message
          ? cause.message
          : "Failed to delete repository",
      );
    } finally {
      setIsBusy(false);
    }
  }, [onDeleted, options, repo.id]);

  /**
   * Ask for confirmation before deleting.
   */
  const confirmDelete = useCallback(() => {
    Alert.alert(
      "Delete repository?",
      `This permanently removes ${repo.name} and all of its data -- the graph, the glossary, the reading order and the chat history. It cannot be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => {
            void handleDelete();
          },
        },
      ],
    );
  }, [handleDelete, repo.name]);

  /**
   * Re-ingest the repository, once the reader has confirmed.
   */
  const handleReingest = useCallback(
    async (payload?: ReingestPayload) => {
      setError(null);
      setIsBusy(true);
      try {
        await reingestRepository(repo.id, payload, options);
        onReingested?.();
      } catch (cause) {
        setError(
          cause instanceof Error && cause.message
            ? cause.message
            : "Failed to start re-ingestion process",
        );
      } finally {
        setIsBusy(false);
      }
    },
    [onReingested, options, repo.id],
  );

  /**
   * Ask for confirmation before re-ingesting.
   */
  const confirmReingest = useCallback(() => {
    Alert.alert(
      "Re-ingest repository?",
      `This deletes the ${repo.name} row and recreates it with the same id, so every row that hangs off it -- the graph, the glossary, the reading order, the embeddings and the chat history -- is deleted with it. The analysis then runs again from scratch.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Re-ingest",
          style: "destructive",
          onPress: () => {
            void handleReingest();
          },
        },
      ],
    );
  }, [handleReingest, repo.name]);

  return (
    <View
      testID="danger-zone"
      className="rounded border border-destructive/30 bg-card p-4"
    >
      <Text className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-destructive">
        Danger Zone
      </Text>

      <Text className="text-[13px] font-medium text-foreground">
        Re-ingest repository
      </Text>
      <Text className="mt-0.5 text-xs text-muted-foreground">
        Re-analyze and rebuild all repository insights.
      </Text>
      <TextInput
        testID="danger-zone-confirmation"
        accessibilityLabel="Type the repository name to confirm"
        value={confirmation}
        onChangeText={setConfirmation}
        placeholder={`Type ${repo.name} to confirm`}
        placeholderTextColor={colors.mutedForeground}
        autoCapitalize="none"
        autoCorrect={false}
        className="mb-2 mt-3 min-h-[44px] rounded border border-border bg-secondary/20 px-3 py-2 text-sm text-foreground"
      />
      <Pressable
        testID="danger-zone-reingest"
        accessibilityRole="button"
        accessibilityLabel="Re-ingest repository"
        accessibilityState={{ disabled: !confirmed || isBusy }}
        disabled={!confirmed || isBusy}
        onPress={confirmReingest}
        className="min-h-[44px] items-center justify-center rounded border border-destructive px-4 active:bg-secondary"
      >
        <Text className="text-[13px] font-semibold text-destructive">
          Re-ingest repository
        </Text>
      </Pressable>

      {parsed ? (
        <>
          <Pressable
            testID="danger-zone-version-toggle"
            accessibilityRole="button"
            accessibilityLabel="Choose a branch or commit to re-ingest"
            accessibilityState={{ expanded: versionPickerOpen }}
            onPress={() => setVersionPickerOpen((open) => !open)}
            className="mt-2 min-h-[44px] items-center justify-center rounded border border-border px-4 active:bg-secondary"
          >
            <Text className="text-[13px] font-medium text-foreground">
              {versionPickerOpen
                ? "Hide branch / commit picker"
                : "Re-ingest a specific branch or commit"}
            </Text>
          </Pressable>

          {versionPickerOpen ? (
            // The same timeline the ingest flow uses: without it the phone
            // could only ever re-analyse the default branch tip, while the
            // web panel lets the reader pin a commit.
            <View className="mt-3 h-[420px]">
              <GitGraph
                owner={parsed.owner}
                repo={parsed.name}
                isSubmitting={isBusy}
                onSelect={(branch, commitSha) => {
                  const target = commitSha
                    ? `commit ${commitSha.slice(0, 7)}`
                    : `branch ${branch}`;
                  // The typed-name confirmation above covers the default
                  // branch; a pinned version goes through the native
                  // confirmation instead, because it deletes just as much.
                  Alert.alert(
                    "Re-ingest repository?",
                    `This deletes ${repo.name} and everything derived from it, then re-analyses ${target} from scratch.`,
                    [
                      { text: "Cancel", style: "cancel" },
                      {
                        text: "Re-ingest",
                        style: "destructive",
                        onPress: () => {
                          void handleReingest({
                            branch,
                            commit_sha: commitSha,
                          });
                        },
                      },
                    ],
                  );
                }}
              />
            </View>
          ) : null}
        </>
      ) : null}

      <View className="my-4 h-px w-full bg-border" />

      <Text className="text-[13px] font-medium text-foreground">
        Delete repository
      </Text>
      <Text className="mt-0.5 text-xs text-muted-foreground">
        Permanently remove this repository and all its data.
      </Text>
      <Pressable
        testID="danger-zone-delete"
        accessibilityRole="button"
        accessibilityLabel="Delete repository"
        accessibilityState={{ disabled: isBusy }}
        disabled={isBusy}
        onPress={confirmDelete}
        className="mt-3 min-h-[44px] items-center justify-center rounded border border-destructive px-4 active:bg-secondary"
      >
        <Text className="text-[13px] font-semibold text-destructive">
          Delete repository
        </Text>
      </Pressable>

      {error ? (
        <View
          testID="danger-zone-error"
          className="mx-0 mb-0 mt-4 rounded border border-destructive/30 bg-destructive/10 p-3"
        >
          <Text className="text-xs text-destructive">{error}</Text>
        </View>
      ) : null}
    </View>
  );
}

export default DangerZone;
