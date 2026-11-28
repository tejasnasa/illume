/**
 * The repository chat screen.
 *
 * @module RepoChatScreen
 *
 * Port of the web client's chat page (``client/src/components/chat/ChatPage.tsx``).
 *
 * Questions are answered by the streaming agent endpoint. The picker chooses
 * the preset -- Auto, Classic, Hybrid, or one of the two deep agent presets,
 * the second of which splits a broad question across parallel workers. The
 * run streams its reasoning, tool calls and searches into the turn as they
 * happen, then the answer with tappable citations. Conversations are listed
 * in a sheet, and an answer whose cited files have changed carries a stale
 * notice. The free tier cannot run agent presets and the picker says so.
 *
 * The keyboard is handled by padding the screen with its reported height;
 * see :mod:`src.hooks.useKeyboardHeight` for why ``KeyboardAvoidingView`` is
 * not enough on Android.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  Text,
  TextInput,
  View,
} from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useGlobalSearchParams } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { getGraph } from "@/api/graph";
import { queryKeys } from "@/api/queryKeys";
import { AdvancedSheet } from "@/components/chat/AdvancedSheet";
import { ConversationSwitcher } from "@/components/chat/ConversationSwitcher";
import { PresetPicker } from "@/components/chat/PresetPicker";
import { TurnView } from "@/components/chat/TurnView";
import { useAuth } from "@/hooks/useAuth";
import { useConversation, type Turn } from "@/hooks/useConversation";
import { useConversationList } from "@/hooks/useConversationList";
import { useKeyboardHeight } from "@/hooks/useKeyboardHeight";
import { useRepository } from "@/hooks/useRepositories";
import { MAX_QUESTION_CHARS } from "@/lib/agent/limits";
import {
  buildOverrides,
  defaultPreset,
  defaultSettings,
  isCustom,
  loadChoice,
  presetAvailability,
  saveChoice,
  type Capabilities,
  type DrawerSettings,
  type PresetChoice,
  type PresetId,
} from "@/lib/agent/presets";
import { buildSuggestions } from "@/lib/agent/suggestions";
import { isReadyStatus } from "@/lib/repoStatus";
import { colors } from "@/theme/tokens";

/**
 * Render the chat screen.
 *
 * @returns The chat screen.
 */
export default function RepoChatScreen() {
  // ``useGlobalSearchParams``, not the local variant: these screens are
  // tab children, not the ``[id]`` segment itself.
  const { id, q } = useGlobalSearchParams<{ id: string; q?: string }>();
  const repoNumber = String(id ?? "");

  const { data: repo, isError: repoError } = useRepository(repoNumber);
  const insets = useSafeAreaInsets();
  const keyboardHeight = useKeyboardHeight();
  const { user, refreshUser } = useAuth();

  // The chat routes are keyed by the repository UUID, so the screen has to
  // resolve the record before it can talk to them.
  const repoId = repo?.id ?? "";

  const caps = useMemo<Capabilities>(
    () => ({
      hasOwnKey: Boolean(user?.has_ai_key),
      supportsTools: user?.ai_supports_tools ?? null,
    }),
    [user?.has_ai_key, user?.ai_supports_tools],
  );

  // The file graph lights up the files a run touched. It shares the graph
  // screen's query key, so it is fetched once however the tabs are used.
  const { data: fileGraph } = useQuery({
    queryKey: queryKeys.repositories.graph(repoId, "file"),
    queryFn: () => getGraph(repoId, "file"),
    enabled: repoId.length > 0 && isReadyStatus(repo?.status),
  });

  const list = useConversationList(repoId);
  const { refresh: refreshList } = list;
  const conversation = useConversation(repoId, null, {
    onTurnSaved: () => {
      void refreshList();
      void refreshUser();
    },
    onMissing: () => conversationSelectRef.current(null),
  });
  const conversationSelectRef = useRef<(id: string | null) => void>(() => {});
  conversationSelectRef.current = conversation.select;
  const { turns, busy, loaded } = conversation;

  const [input, setInput] = useState(typeof q === "string" ? q : "");
  const [choice, setChoice] = useState<PresetChoice>(() => defaultPreset(caps));
  const [settings, setSettings] = useState<DrawerSettings | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const listRef = useRef<FlatList<Turn>>(null);

  // The account default depends on the profile, which may arrive after the
  // first render; follow it until the reader or a stored choice takes over.
  const touchedRef = useRef(false);
  useEffect(() => {
    if (!touchedRef.current) setChoice(defaultPreset(caps));
  }, [caps]);

  // The remembered choice is read after mount.
  useEffect(() => {
    if (!repoId) return;
    let cancelled = false;
    void loadChoice(repoId).then((stored) => {
      if (cancelled || !stored) return;
      if (!presetAvailability(stored.preset, caps).available) return;
      touchedRef.current = true;
      setChoice(stored.preset);
      setSettings(stored.settings);
    });
    return () => {
      cancelled = true;
    };
    // Only on first load for this repository.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId]);

  // The sheet tunes a concrete preset; under Auto it starts from the account
  // default, and Auto itself sends no overrides because the server has not
  // yet chosen the preset they would apply to.
  const preset: PresetId = choice === "auto" ? defaultPreset(caps) : choice;
  const effective = settings ?? defaultSettings(preset);
  const custom = choice !== "auto" && isCustom(preset, effective);

  const remember = useCallback(
    (nextChoice: PresetChoice, nextSettings: DrawerSettings | null) => {
      touchedRef.current = true;
      setChoice(nextChoice);
      setSettings(nextSettings);
      void saveChoice(repoId, { preset: nextChoice, settings: nextSettings });
    },
    [repoId],
  );

  const freeChatRemaining =
    user && !user.has_ai_key
      ? Math.max(0, user.free_chat_messages_limit - user.free_chat_messages_used)
      : null;
  const quotaExhausted = freeChatRemaining !== null && freeChatRemaining <= 0;

  const canSend =
    !busy &&
    input.trim().length > 0 &&
    input.length <= MAX_QUESTION_CHARS &&
    !quotaExhausted &&
    Boolean(repo);

  const ask = useCallback(
    (question: string) => {
      conversation.send(
        question,
        choice,
        choice === "auto" ? undefined : buildOverrides(preset, effective),
      );
    },
    [conversation, choice, preset, effective],
  );

  const handleSend = useCallback(() => {
    if (!canSend) return;
    const question = input.trim();
    setInput("");
    ask(question);
  }, [canSend, input, ask]);

  const suggestions = useMemo(
    () =>
      repo
        ? buildSuggestions({
            name: repo.name,
            entryPoints: repo.entry_points,
            criticalFile: null,
          })
        : [],
    [repo],
  );

  const scrollToNewest = useCallback(() => {
    listRef.current?.scrollToEnd({ animated: false });
  }, []);

  if (repoError) {
    return (
      <View testID="chat-screen" className="flex-1">
        <View className="mx-4 mt-4 rounded-sm border border-destructive/30 bg-destructive/10 p-3">
          <Text className="text-xs text-destructive">
            This repository could not be loaded.
          </Text>
        </View>
      </View>
    );
  }

  if (!repo) {
    return (
      <View testID="chat-screen" className="flex-1 items-center justify-center">
        <ActivityIndicator color={colors.mutedForeground} />
      </View>
    );
  }

  // The chat endpoint refuses a repository that has not been indexed.
  if (!isReadyStatus(repo.status)) {
    return (
      <View testID="chat-screen" className="flex-1 items-center justify-center p-6">
        <Text className="mb-2 font-pixel text-base text-foreground">
          Not indexed yet
        </Text>
        <Text className="max-w-[280px] text-center text-[13px] text-muted-foreground">
          This repository is still being indexed. Questions can be asked once it
          is ready.
        </Text>
      </View>
    );
  }

  const repoRef = {
    url: repo.github_url,
    commitSha: repo.ingested_commit_sha,
    branch: repo.ingested_branch,
  };

  return (
    <View
      testID="chat-screen"
      // The keyboard height is added directly; the bottom inset sits on top
      // because the reported height stops at the gesture bar.
      style={{
        paddingBottom: keyboardHeight > 0 ? keyboardHeight + insets.bottom : 0,
      }}
      className="flex-1"
    >
      <View className="flex-row items-center justify-between gap-2 border-b border-border px-4 py-2">
        <Pressable
          testID="open-conversations"
          accessibilityRole="button"
          accessibilityLabel="Conversations"
          onPress={() => setSwitcherOpen(true)}
          className="h-9 flex-row items-center gap-1.5 rounded-sm border border-input px-3"
        >
          <Text className="font-pixel text-[11px] uppercase tracking-[0.7px] text-zinc-300">
            Chats{list.items.length > 0 ? ` (${list.items.length})` : ""}
          </Text>
        </Pressable>

        {freeChatRemaining !== null ? (
          <Text
            testID="chat-free-remaining"
            className="font-pixel text-[10px] uppercase text-muted-foreground"
          >
            {freeChatRemaining} free {freeChatRemaining === 1 ? "question" : "questions"} left
          </Text>
        ) : null}

        <PresetPicker
          value={choice}
          custom={custom}
          caps={caps}
          disabled={busy}
          onChange={(next) => remember(next, null)}
          onOpenAdvanced={() => setAdvancedOpen(true)}
        />
      </View>

      <FlatList
        ref={listRef}
        testID="chat-list"
        data={turns}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <View className="mb-6">
            <TurnView
              turn={item}
              repo={repoRef}
              repoId={repoId}
              graph={fileGraph ?? null}
              onReask={busy ? undefined : ask}
              onDelete={(turnId) => void conversation.remove(turnId)}
            />
          </View>
        )}
        onContentSizeChange={scrollToNewest}
        keyboardShouldPersistTaps="handled"
        className="flex-1"
        contentContainerClassName="p-4"
        ListEmptyComponent={
          !loaded ? (
            <View testID="chat-loading" className="items-center py-16">
              <ActivityIndicator color={colors.mutedForeground} />
            </View>
          ) : (
            <View testID="chat-empty" className="gap-3 py-8">
              <Text className="font-pixel text-base text-foreground">
                Ask about {repo.name}
              </Text>
              {suggestions.map((question) => (
                <Pressable
                  key={question}
                  testID="chat-suggestion"
                  accessibilityRole="button"
                  disabled={quotaExhausted}
                  onPress={() => ask(question)}
                  className="rounded-sm border border-border bg-card p-3 active:border-accent"
                >
                  <Text className="text-[13px] text-zinc-300">{question}</Text>
                </Pressable>
              ))}
            </View>
          )
        }
      />

      {quotaExhausted ? (
        <View className="mx-3 mb-2 rounded-sm border border-primary/30 bg-primary/10 px-3 py-2">
          <Text className="text-[11px] text-muted-foreground">
            You have used the free chat questions. Add your own API key to keep
            chatting.
          </Text>
        </View>
      ) : null}

      <View
        className="border-t border-border p-3"
        style={{ paddingBottom: 12 }}
      >
        <View className="flex-row items-end gap-2">
          <TextInput
            testID="chat-input"
            accessibilityLabel="Ask about the codebase"
            value={input}
            onChangeText={setInput}
            placeholder={
              quotaExhausted ? "Free chat allowance used up." : "Ask about the codebase…"
            }
            placeholderTextColor={colors.mutedForeground}
            editable={!quotaExhausted}
            multiline
            className="max-h-[120px] min-h-[44px] flex-1 rounded-sm border border-input bg-card px-3 py-2 text-[14px] text-foreground"
          />
          {busy ? (
            <Pressable
              testID="chat-stop"
              accessibilityRole="button"
              accessibilityLabel="Stop"
              onPress={conversation.stop}
              className="h-11 items-center justify-center rounded-sm border border-input px-4"
            >
              <Text className="font-pixel text-xs uppercase text-zinc-300">Stop</Text>
            </Pressable>
          ) : (
            <Pressable
              testID="chat-send"
              accessibilityRole="button"
              accessibilityLabel="Send"
              accessibilityState={{ disabled: !canSend }}
              disabled={!canSend}
              onPress={handleSend}
              className={`h-11 items-center justify-center rounded-sm bg-primary px-4 ${canSend ? "" : "opacity-40"}`}
            >
              <Text className="font-pixel text-xs uppercase text-primary-foreground">
                Send
              </Text>
            </Pressable>
          )}
        </View>
      </View>

      <ConversationSwitcher
        open={switcherOpen}
        items={list.items}
        activeId={conversation.activeId}
        loaded={list.loaded}
        onClose={() => setSwitcherOpen(false)}
        onOpen={(cid) => conversation.select(cid)}
        onNew={() => conversation.select(null)}
        onRename={list.rename}
        onDelete={(cid) => {
          if (cid === conversation.activeId) conversation.select(null);
          void list.remove(cid);
        }}
      />

      <AdvancedSheet
        open={advancedOpen}
        preset={preset}
        settings={effective}
        caps={caps}
        onClose={() => setAdvancedOpen(false)}
        onPreset={(next) => remember(next, null)}
        onChange={(next) => remember(choice === "auto" ? preset : choice, next)}
      />
    </View>
  );
}
