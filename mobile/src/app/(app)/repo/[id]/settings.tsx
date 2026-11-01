/**
 * The settings of one repository.
 *
 * Every control here acts on the repository the shell is showing, which is
 * why they live under ``repo/[id]/`` rather than in the global settings
 * list: the global list had to ask which repository was meant, and a
 * screen that has to ask is a screen that can act on the wrong one.
 *
 * The account-level things -- the AI credential, contact, the account
 * itself -- stay in the global settings list, because none of them belong
 * to a repository.
 *
 * @module RepoSettingsScreen
 */

import { useCallback } from "react";
import { ActivityIndicator, ScrollView, Text, View } from "react-native";
import { router, useGlobalSearchParams } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useQueryClient } from "@tanstack/react-query";

import { AutoUpdateSection } from "@/components/AutoUpdateSection";
import { DangerZone } from "@/components/DangerZone";
import { ExportIllumeButton } from "@/components/ExportIllumeButton";
import { queryKeys } from "@/api/queryKeys";
import { useRepository } from "@/hooks/useRepositories";
import { colors } from "@/theme/tokens";

export default function RepoSettingsScreen() {
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const { id } = useGlobalSearchParams<{ id: string }>();
  const repoNumber = String(id ?? "");

  const { data: repo, isLoading, isError } = useRepository(repoNumber);

  /**
   * Leave after a destructive action, with the cache made honest.
   *
   * @param deleted - True when the repository no longer exists.
   */
  const leave = useCallback(
    (deleted: boolean) => {
      if (deleted) {
        queryClient.removeQueries({ queryKey: queryKeys.repositories.all });
      } else {
        queryClient.invalidateQueries({ queryKey: queryKeys.repositories.all });
      }
      router.dismissTo("/(app)/dashboard");
    },
    [queryClient],
  );

  // The shell above this screen already carries the repository's identity
  // and its safe-area inset, and the tab bar is the way back, so this screen
  // draws no header of its own.
  if (isLoading || !repo) {
    return (
      <View className="flex-1 items-center justify-center bg-background">
        {isError ? (
          <Text className="text-[13px] text-muted-foreground">
            This repository could not be loaded.
          </Text>
        ) : (
          <ActivityIndicator size="large" color={colors.foreground} />
        )}
      </View>
    );
  }

  return (
    <View className="flex-1 bg-background">
      <ScrollView
        testID="repo-settings-scroll"
        automaticallyAdjustKeyboardInsets
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{
          padding: 16,
          paddingBottom: insets.bottom + 32,
        }}
      >
        <AutoUpdateSection
          repo={repo}
          onChanged={() => {
            void queryClient.invalidateQueries({
              queryKey: queryKeys.repositories.detail(repo.id),
            });
          }}
        />

        <Text className="mb-2 mt-6 text-[11px] font-bold uppercase tracking-[2px] text-muted-foreground opacity-60">
          Export
        </Text>
        <View className="rounded border border-border bg-card p-4">
          <Text className="text-[13px] font-medium text-foreground">
            Export .illume file
          </Text>
          <Text className="mb-3 mt-0.5 text-xs text-muted-foreground">
            A compressed context file for this repository, written to the
            device and handed to the share sheet.
          </Text>
          <ExportIllumeButton
            repoId={repo.id}
            repoName={repo.name}
            label="Export"
            testID="repo-settings-export"
          />
        </View>

        <View className="mt-6">
          <DangerZone
            repo={repo}
            onDeleted={() => leave(true)}
            onReingested={() => leave(false)}
          />
        </View>
      </ScrollView>
    </View>
  );
}
