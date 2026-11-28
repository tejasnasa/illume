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

import { useCallback, useState } from "react";
import {
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { GitGraph } from "@/components/GitGraph";
import { useAuth } from "@/hooks/useAuth";
import { useGitHubRepos } from "@/hooks/useGitHubRepos";
import { useRepoForm } from "@/hooks/useRepoForm";
import { PIXEL_FONT } from "@/lib/fonts";
import { parseGitHubRepoUrl } from "@/lib/githubUrl";
import { timeAgo } from "@/lib/timeAgo";
import { colors } from "@/theme/tokens";
import { Blink } from "@/ui/Blink";
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

/** The two sources of repositories, in tab order. */
const TABS: { id: Tab; label: string }[] = [
  { id: "my-repos", label: "My Repositories" },
  { id: "external", label: "External URL" },
];

/** The steps of the flow, as the header names them. */
const STEPS = ["Repository", "Version"] as const;

/**
 * The step indicator across the top of the picker.
 *
 * @param props - The zero-based index of the step on screen.
 * @returns The ordered step list.
 */
function StepHeader({ current }: { current: number }) {
  return (
    <View accessibilityRole="header" className="flex-row items-center gap-2.5">
      {STEPS.map((step, i) => {
        const color =
          i === current
            ? "text-accent"
            : i < current
              ? "text-zinc-300"
              : "text-faint-foreground";
        return (
          <View key={step} className="flex-row items-center gap-2.5">
            {i > 0 ? <View className="h-px w-5 bg-border-strong" /> : null}
            <Text
              className={`text-[11px] uppercase tracking-[1.4px] ${color}`}
              style={{ fontFamily: PIXEL_FONT }}
            >
              {`${i + 1} ${step}`}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

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

  const header = (
    <View className="flex-row items-center justify-between gap-4 border-b border-border px-4 py-3">
      <StepHeader current={mode === "picker" ? 0 : 1} />
      {/* A modal route has no visible dismissal of its own: the hardware
          back button is the only way out on Android, and on iOS the reader
          has to know the sheet can be swiped. This is the explicit exit. */}
      <Pressable
        testID="repo-picker-cancel"
        accessibilityRole="button"
        accessibilityLabel="Cancel adding a repository"
        onPress={() => onClose?.(null)}
        hitSlop={8}
        className="h-[44px] w-[44px] items-center justify-center"
      >
        <Text
          className="text-base text-subtle-foreground"
          style={{ fontFamily: PIXEL_FONT }}
        >
          ✕
        </Text>
      </Pressable>
    </View>
  );

  if (mode === "graph") {
    return (
      <View className="flex-1 bg-background" style={{ paddingTop: insets.top }}>
        {header}
        <ScrollView
          keyboardShouldPersistTaps="handled"
          contentContainerClassName="px-4 pt-5"
          contentContainerStyle={{ paddingBottom: insets.bottom + 16 }}
        >
          <View className="gap-1.5 pb-4">
            <Text
              className="text-2xl leading-[30px] text-foreground"
              style={{ fontFamily: PIXEL_FONT }}
            >
              {"Choose a version of "}
              <Text className="text-accent">
                {selectedOwner}/{selectedName}
              </Text>
            </Text>
            <Text className="text-sm leading-[20px] text-muted-foreground">
              Read the tip of a branch, or pin any older commit as a snapshot.
              The default branch is picked for you.
            </Text>
          </View>

          {ingestError ? (
            <View
              accessibilityRole="alert"
              className="mb-4 rounded-sm border border-red-500/25 bg-red-500/5 p-3"
            >
              <Text className="text-xs text-red-300">{ingestError}</Text>
              {quotaExceeded ? (
                <Text className="mt-1 text-[11px] text-muted-foreground">
                  Add your own API key in Settings to keep ingesting.
                </Text>
              ) : null}
            </View>
          ) : null}

          <GitGraph
            owner={selectedOwner}
            repo={selectedName}
            onSelect={handleVersionSelect}
            isSubmitting={isSubmitting}
            onBack={() => setMode("picker")}
          />
        </ScrollView>
      </View>
    );
  }

  return (
    <View className="flex-1 bg-background" style={{ paddingTop: insets.top }}>
      {header}
      <View className="gap-1.5 px-4 pt-5">
        <Text
          className="text-2xl text-foreground"
          style={{ fontFamily: PIXEL_FONT }}
        >
          {"Add a "}
          <Text className="text-accent">repository</Text>
        </Text>
        <Text className="text-sm text-muted-foreground">
          Pick one of yours, or paste any public GitHub URL.
        </Text>
      </View>

      <View
        accessibilityRole="tablist"
        className="mt-4 flex-row gap-6 border-b border-border px-4"
      >
        {TABS.map(({ id, label }) => {
          const on = activeTab === id;
          return (
            <Pressable
              key={id}
              testID={`repo-picker-tab-${id}`}
              accessibilityRole="tab"
              accessibilityState={{ selected: on }}
              onPress={() => setActiveTab(id)}
              className={`-mb-px min-h-[44px] justify-center border-b-2 ${
                on ? "border-accent" : "border-transparent"
              }`}
            >
              <Text
                className={`text-xs uppercase tracking-[1.2px] ${
                  on ? "text-foreground" : "text-subtle-foreground"
                }`}
                style={{ fontFamily: PIXEL_FONT }}
              >
                {label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {activeTab === "my-repos" ? (
        <View className="flex-1">
          <View className="px-4 pb-3 pt-4">
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
            // Without this the first tap after typing a search only
            // dismisses the keyboard, and the repository needs a second tap.
            keyboardShouldPersistTaps="handled"
            keyExtractor={(repo) => repo.full_name}
            contentContainerStyle={{
              paddingHorizontal: 16,
              paddingBottom: insets.bottom + 24,
            }}
            onEndReachedThreshold={0.4}
            onEndReached={() => {
              if (hasMore && !isLoading) void fetchMore();
            }}
            renderItem={({ item }) => {
              const [owner] = item.full_name.split("/");
              return (
                <Pressable
                  testID={`repo-picker-item-${item.full_name}`}
                  accessibilityRole="button"
                  accessibilityLabel={`Select ${item.name}`}
                  onPress={() => handleSelectMyRepo(item)}
                  className="mb-1.5 min-h-[44px] gap-2 rounded-sm border border-border bg-background px-3.5 py-3 active:bg-secondary"
                >
                  <View className="flex-row items-center justify-between gap-3">
                    <Text
                      numberOfLines={1}
                      className="min-w-0 flex-1 text-sm"
                      style={{ fontFamily: PIXEL_FONT }}
                    >
                      <Text className="text-subtle-foreground">{owner}/</Text>
                      <Text className="text-foreground">{item.name}</Text>
                    </Text>
                    <Text
                      className="text-sm text-faint-foreground"
                      style={{ fontFamily: PIXEL_FONT }}
                    >
                      →
                    </Text>
                  </View>
                  <Text
                    className="text-[13px] text-muted-foreground"
                    numberOfLines={1}
                  >
                    {item.description || "No description provided."}
                  </Text>
                  <View className="flex-row flex-wrap items-center gap-2">
                    {item.private ? (
                      <View className="border border-warning/40 px-1.5 py-0.5">
                        <Text
                          className="text-[10px] uppercase tracking-[0.8px] text-warning"
                          style={{ fontFamily: PIXEL_FONT }}
                        >
                          Private
                        </Text>
                      </View>
                    ) : null}
                    {item.language ? (
                      <View className="border border-border px-1.5 py-0.5">
                        <Text
                          className="text-[10px] uppercase tracking-[0.8px] text-zinc-300"
                          style={{ fontFamily: PIXEL_FONT }}
                        >
                          {item.language}
                        </Text>
                      </View>
                    ) : null}
                    {item.updated_at ? (
                      <Text
                        className="text-[10px] uppercase tracking-[0.8px] text-faint-foreground"
                        style={{ fontFamily: PIXEL_FONT }}
                      >
                        {`Pushed ${timeAgo(new Date(item.updated_at))}`}
                      </Text>
                    ) : null}
                  </View>
                </Pressable>
              );
            }}
            ListEmptyComponent={
              isLoading ? (
                <Blink>
                  <Text
                    className="py-8 text-center text-xs uppercase tracking-[1.4px] text-muted-foreground"
                    style={{ fontFamily: PIXEL_FONT }}
                  >
                    Loading repositories...
                  </Text>
                </Blink>
              ) : isError ? (
                <Text
                  accessibilityRole="alert"
                  className="py-12 text-center text-sm text-red-300"
                >
                  {error?.message ?? "Failed to load repositories"}
                </Text>
              ) : (
                <Text className="py-12 text-center text-sm text-muted-foreground">
                  {search.trim()
                    ? "No GitHub repositories match your search."
                    : "No GitHub repositories found."}
                </Text>
              )
            }
            ListFooterComponent={
              isLoading && repos.length > 0 ? (
                <Blink>
                  <Text
                    className="py-4 text-center text-xs uppercase tracking-[1.4px] text-muted-foreground"
                    style={{ fontFamily: PIXEL_FONT }}
                  >
                    Loading repositories...
                  </Text>
                </Blink>
              ) : null
            }
          />
        </View>
      ) : (
        <KeyboardAvoidingView
          className="flex-1 justify-between gap-6 p-4"
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={{ paddingBottom: insets.bottom + 16 }}
        >
          <View className="gap-2">
            <Text
              className="text-[11px] uppercase tracking-[1.4px] text-muted-foreground"
              style={{ fontFamily: PIXEL_FONT }}
            >
              GitHub Repository URL
            </Text>
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
              <Text className="text-xs text-destructive">{externalError}</Text>
            ) : (
              <Text
                className="text-[11px] uppercase tracking-[0.8px] text-subtle-foreground"
                style={{ fontFamily: PIXEL_FONT }}
              >
                Public repositories only. For a private one, use the My
                Repositories tab.
              </Text>
            )}
          </View>

          <Pressable
            testID="repo-picker-external-continue"
            accessibilityRole="button"
            accessibilityLabel="Continue"
            onPress={handleExternalSubmit}
            className="min-h-[44px] items-center justify-center self-end rounded-sm bg-primary px-5 active:opacity-80"
          >
            <Text
              className="text-[13px] uppercase tracking-[0.8px] text-primary-foreground"
              style={{ fontFamily: PIXEL_FONT }}
            >
              Continue →
            </Text>
          </Pressable>
        </KeyboardAvoidingView>
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
    <TextInput
      testID={testID}
      accessibilityLabel={placeholder}
      value={value}
      onChangeText={onChangeText}
      placeholder={placeholder}
      placeholderTextColor={colors.faintForeground}
      selectionColor={colors.accent}
      className="h-[44px] rounded-sm border border-input bg-background px-3.5 text-sm text-foreground"
      {...rest}
    />
  );
}

export default RepoPickerModal;
