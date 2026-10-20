/**
 * Two-step repository picker: choose a repo, then choose a version.
 *
 * @module RepoPickerModal
 *
 * Port of ``client/src/components/RepoPickerModal.tsx``. The web version
 * renders inside a centred ``<Modal>``; on a phone that wastes the screen
 * and fights the keyboard, so this is a **full-screen modal route**
 * (see ``src/app/(app)/repo-picker.tsx``).
 *
 * The two steps are the same:
 *
 * 1. **Pick a repository** -- either from the user's GitHub account (with
 *    a name filter) or by pasting an external URL.
 * 2. **Pick a version** -- the git graph, where a branch and optionally a
 *    commit are chosen and the ingest is triggered.
 *
 * The ingest itself posts to ``/api/v1/repository``. On success the
 * picker reports the new repository's number through ``onClose``; the
 * route that hosts the picker decides what the navigation looks like
 * (see ``src/app/(app)/repo-picker.tsx``).
 */

import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { GitGraph } from "@/components/GitGraph";
import { useAuth } from "@/hooks/useAuth";
import { useGitHubRepos } from "@/hooks/useGitHubRepos";
import { useRepoForm } from "@/hooks/useRepoForm";
import { parseGitHubRepoUrl } from "@/lib/githubUrl";
import { colors } from "@/theme/tokens";
import type { GitHubRepo } from "@/types/github";

/** Props for the repository picker modal. */
export interface RepoPickerModalProps {
  /**
   * Called once ingestion has been queued.
   *
   * @param repoNum - The new repository's user-scoped number, or ``null``
   *   when the picker was dismissed without creating anything.
   */
  onClose?: (repoNum: number | null) => void;
}

/** Which step of the flow is showing. */
type Mode = "picker" | "graph";

/** Which source of repositories is showing. */
type Tab = "my-repos" | "external";

/**
 * Lets users choose a GitHub repo, then a branch/commit to ingest.
 *
 * @param onClose - Called with the new repository's number on success, or
 *   with ``null`` when the picker was dismissed.
 * @returns Picker UI or version graph depending on the current mode.
 */
export function RepoPickerModal({ onClose }: RepoPickerModalProps) {
  const [mode, setMode] = useState<Mode>("picker");
  const [activeTab, setActiveTab] = useState<Tab>("my-repos");
  const insets = useSafeAreaInsets();

  const [selectedOwner, setSelectedOwner] = useState("");
  const [selectedName, setSelectedName] = useState("");
  const [selectedUrl, setSelectedUrl] = useState("");

  const [externalUrl, setExternalUrl] = useState("");
  const [externalError, setExternalError] = useState("");

  const {
    repos,
    isLoading,
    isError,
    error,
    hasMore,
    fetchMore,
    search,
    setSearch,
  } = useGitHubRepos();

  const { submit, isSubmitting, ingestError, quotaExceeded, clearError } =
    useRepoForm();
  const { refreshUser } = useAuth();

  /**
   * Records the clicked repo and advances to version selection.
   *
   * @param repo - Repository chosen from the list.
   */
  const handleSelectMyRepo = useCallback((repo: GitHubRepo) => {
    const [owner, name] = repo.full_name.split("/");
    setSelectedOwner(owner);
    setSelectedName(name);
    setSelectedUrl(repo.html_url);
    setMode("graph");
  }, []);

  /**
   * Validates an external GitHub URL and advances to version selection.
   *
   * @returns True when the URL was accepted.
   */
  const handleExternalSubmit = useCallback((): boolean => {
    setExternalError("");

    const parsed = parseGitHubRepoUrl(externalUrl);
    if (!parsed) {
      setExternalError(
        "Please enter a valid GitHub repository URL (e.g. https://github.com/user/repo)",
      );
      return false;
    }

    setSelectedOwner(parsed.owner);
    setSelectedName(parsed.name);
    setSelectedUrl(`https://github.com/${parsed.owner}/${parsed.name}`);
    setMode("graph");
    return true;
  }, [externalUrl]);

  /**
   * Posts the chosen branch/commit to start ingestion.
   *
   * @param branch - Branch to ingest.
   * @param commitSha - Optional pinned commit; null ingests the branch tip.
   */
  const handleVersionSelect = useCallback(
    async (branch: string, commitSha: string | null) => {
      clearError();
      const created = await submit({
        github_url: selectedUrl,
        branch,
        commit_sha: commitSha,
      });
      if (created) {
        // The creation consumed a free ingestion slot, so the dashboard's
        // allowance banner is now stale. Re-read the profile before the
        // user gets back to it.
        void refreshUser();
        onClose?.(created.repo_num);
      }
    },
    [clearError, onClose, refreshUser, selectedUrl, submit],
  );

  const tabButton = useMemo(
    () => (tab: Tab, label: string) => {
      const isActive = activeTab === tab;
      return (
        <Pressable
          testID={`repo-picker-tab-${tab}`}
          accessibilityRole="tab"
          accessibilityState={{ selected: isActive }}
          onPress={() => setActiveTab(tab)}
          className={`flex-1 items-center justify-center border-b-2 py-3 ${
            isActive
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground"
          }`}
        >
          <Text
            className={`text-[11px] font-bold uppercase tracking-wider ${
              isActive ? "text-foreground" : "text-muted-foreground"
            }`}
          >
            {label}
          </Text>
        </Pressable>
      );
    },
    [activeTab],
  );

  if (mode === "graph") {
    return (
      <View className="flex-1 bg-background" style={{ paddingTop: insets.top }}>
        <View className="flex-row items-center gap-2 px-4 pb-2 pt-3">
          <Pressable
            testID="repo-picker-back"
            accessibilityRole="button"
            accessibilityLabel="Back to repository list"
            onPress={() => setMode("picker")}
            hitSlop={8}
            className="rounded px-1.5 py-1 active:bg-secondary"
          >
            <Text className="text-xs text-muted-foreground">
              ← Back to repository list
            </Text>
          </Pressable>
        </View>

        <View className="px-4 pb-3">
          <Text className="text-xl font-bold text-foreground">
            Configure Version for {selectedOwner}/{selectedName}
          </Text>
          <Text className="mt-1 text-xs text-muted-foreground">
            Select a branch or commit from the git history to ingest a targeted
            snapshot.
          </Text>
        </View>

        {ingestError ? (
          <View className="mx-4 mb-3 rounded border border-destructive/30 bg-destructive/10 p-3">
            <Text className="text-xs text-destructive">{ingestError}</Text>
            {quotaExceeded ? (
              <Text className="mt-1 text-[11px] text-muted-foreground">
                Add your own API key in Settings to keep ingesting.
              </Text>
            ) : null}
          </View>
        ) : null}

        <View
          className="flex-1 px-4"
          style={{ paddingBottom: insets.bottom + 16 }}
        >
          <GitGraph
            owner={selectedOwner}
            repo={selectedName}
            onSelect={handleVersionSelect}
            isSubmitting={isSubmitting}
          />
        </View>
      </View>
    );
  }

  return (
    <View className="flex-1 bg-background" style={{ paddingTop: insets.top }}>
      <View className="flex-row border-b border-border">
        {tabButton("my-repos", "My Repositories")}
        {tabButton("external", "External URL")}
      </View>

      {activeTab === "my-repos" ? (
        <View className="flex-1">
          <View className="px-4 pb-3 pt-3">
            <TextInputRow
              testID="repo-picker-search"
              value={search}
              onChangeText={setSearch}
              placeholder="Search your GitHub repositories..."
            />
          </View>

          <FlatList
            testID="repo-picker-list"
            data={repos}
            keyExtractor={(repo) => repo.full_name}
            contentContainerStyle={{
              paddingHorizontal: 16,
              paddingBottom: insets.bottom + 24,
            }}
            onEndReachedThreshold={0.4}
            onEndReached={() => {
              if (hasMore && !isLoading) void fetchMore();
            }}
            renderItem={({ item }) => (
              <Pressable
                testID={`repo-picker-item-${item.full_name}`}
                accessibilityRole="button"
                accessibilityLabel={`Select ${item.name}`}
                onPress={() => handleSelectMyRepo(item)}
                className="mb-2 flex-row items-center justify-between rounded border border-border bg-secondary/5 px-3 py-3 active:border-primary"
              >
                <View className="min-w-0 flex-1 pr-3">
                  <Text
                    className="text-sm font-semibold text-foreground"
                    numberOfLines={1}
                  >
                    {item.name}
                  </Text>
                  <Text
                    className="mt-0.5 text-xs text-muted-foreground"
                    numberOfLines={1}
                  >
                    {item.description || "No description provided."}
                  </Text>
                </View>
                <View className="flex-row items-center gap-2">
                  {item.language ? (
                    <View className="rounded bg-secondary px-1.5 py-0.5">
                      <Text className="font-mono text-[10px] text-muted-foreground">
                        {item.language}
                      </Text>
                    </View>
                  ) : null}
                  {item.private ? (
                    <View className="rounded-full bg-yellow-500/15 px-1.5 py-0.5">
                      <Text className="text-[9px] font-bold uppercase tracking-wider text-yellow-500">
                        Private
                      </Text>
                    </View>
                  ) : null}
                </View>
              </Pressable>
            )}
            ListEmptyComponent={
              isLoading ? (
                <View className="items-center justify-center gap-2 py-10">
                  <ActivityIndicator size="small" color={colors.primary} />
                  <Text className="text-xs text-muted-foreground">
                    Loading repositories...
                  </Text>
                </View>
              ) : isError ? (
                <View className="items-center justify-center gap-2 py-10">
                  <Text className="text-center text-xs text-destructive">
                    {error?.message ?? "Failed to load repositories"}
                  </Text>
                </View>
              ) : (
                <View className="items-center justify-center py-12">
                  <Text className="text-center text-xs italic text-muted-foreground">
                    {search.trim()
                      ? "No GitHub repositories match your search."
                      : "No GitHub repositories found."}
                  </Text>
                </View>
              )
            }
            ListFooterComponent={
              isLoading && repos.length > 0 ? (
                <View className="items-center justify-center py-3">
                  <ActivityIndicator size="small" color={colors.primary} />
                </View>
              ) : null
            }
          />
        </View>
      ) : (
        <View
          className="flex-1 justify-between px-4 py-4"
          style={{ paddingBottom: insets.bottom + 16 }}
        >
          <View>
            <TextInputRow
              testID="repo-picker-external-url"
              value={externalUrl}
              onChangeText={(value) => {
                setExternalUrl(value);
                if (externalError) setExternalError("");
              }}
              placeholder="https://github.com/owner/repository"
              keyboardType="url"
              autoCapitalize="none"
              autoCorrect={false}
            />
            {externalError ? (
              <Text className="mt-2 text-xs text-destructive">
                {externalError}
              </Text>
            ) : null}
          </View>

          <Pressable
            testID="repo-picker-external-continue"
            accessibilityRole="button"
            onPress={handleExternalSubmit}
            className="min-h-[48px] w-full items-center justify-center rounded bg-primary"
          >
            <Text className="text-sm font-semibold text-primary-foreground">
              Continue
            </Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

/**
 * A plain single-line text field.
 *
 * Kept local rather than pulling in the shared :component:`Input` because
 * the two fields in this screen are visually identical and neither takes
 * a floating label.
 */
function TextInputRow({
  value,
  onChangeText,
  placeholder,
  testID,
  ...rest
}: {
  value: string;
  onChangeText: (value: string) => void;
  placeholder: string;
  testID?: string;
  keyboardType?: "default" | "url";
  autoCapitalize?: "none" | "sentences";
  autoCorrect?: boolean;
}) {
  return (
    <View>
      <TextInput
        testID={testID}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor="#71717b"
        className="min-h-[44px] rounded border border-border bg-secondary/10 px-3 py-2.5 text-sm text-foreground"
        {...rest}
      />
    </View>
  );
}

export default RepoPickerModal;
