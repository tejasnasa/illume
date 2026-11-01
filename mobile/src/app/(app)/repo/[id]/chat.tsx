/**
 * The repository chat screen.
 *
 * @module RepoChatScreen
 *
 * Port of the web client's chat panel (``client/src/components/Chat.tsx``).
 *
 * On the web the panel sits beside the repository overview, half the
 * width of a desktop screen. On a phone there is no room for a
 * side-by-side, so the chat is a screen of its own: the history fills it,
 * and the composer is pinned to the bottom.
 *
 * The screen is a hidden tab of the repository shell -- it has its own URL
 * (``/repo/<number>/chat``) but it is not one of the four tabs in the bar.
 *
 * The keyboard is the thing a phone layout has to solve that a desktop
 * panel never had to: the composer has to rise above the keyboard rather
 * than hide behind it. The screen pads itself by the keyboard's reported
 * height -- see :mod:`src.hooks.useKeyboardHeight` for why
 * ``KeyboardAvoidingView`` is not enough here.
 */

import { useCallback, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  Text,
  TextInput,
  View,
} from "react-native";
import { useGlobalSearchParams } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ChatBubble } from "@/components/ChatBubble";
import { useAuth } from "@/hooks/useAuth";
import { useChat, type ChatTurn } from "@/hooks/useChat";
import { useKeyboardHeight } from "@/hooks/useKeyboardHeight";
import { useRepository } from "@/hooks/useRepositories";
import { isReadyStatus } from "@/lib/repoStatus";
import { colors } from "@/theme/tokens";

/**
 * Render the chat screen.
 *
 * @returns The chat screen.
 */
export default function RepoChatScreen() {
  // ``useGlobalSearchParams``, not the local variant: these screens are
  // tab children, not the ``[id]`` segment itself, and a local lookup
  // only sees the current route's own params -- which is why every
  // screen here used to receive an empty id and render nothing.
  const { id } = useGlobalSearchParams<{ id: string }>();
  const repoNumber = String(id ?? "");

  const { data: repo, isError: repoError } = useRepository(repoNumber);
  const insets = useSafeAreaInsets();
  const keyboardHeight = useKeyboardHeight();

  // The chat routes are keyed by the repository's UUID, so the screen has
  // to resolve the record before it can talk to them.
  const repoId = repo?.id ?? "";
  const {
    messages,
    isLoading,
    isLoadingHistory,
    sendMessage,
    deleteMessage,
    clearHistory,
  } = useChat({ repoId, enabled: repoId.length > 0 });

  const { user, refreshUser } = useAuth();

  /**
   * The free chat questions the reader has left.
   *
   * ``null`` means the count does not apply -- a reader with their own
   * API key is never gated. At zero the composer disables itself, which
   * mirrors the server's 402 before a request is spent.
   */
  const freeChatRemaining =
    user && !user.has_ai_key
      ? Math.max(
          0,
          user.free_chat_messages_limit - user.free_chat_messages_used,
        )
      : null;

  const quotaExhausted = freeChatRemaining !== null && freeChatRemaining <= 0;

  const [input, setInput] = useState("");
  const listRef = useRef<FlatList<ChatTurn>>(null);

  const canSend =
    !isLoading && input.trim().length > 0 && !quotaExhausted && !!repo;

  /**
   * Send the composer text and empty the composer.
   *
   * The profile is refreshed afterwards: the free-tier counter lives on it,
   * and without this the "N free questions left" line never moves and the
   * composer stays enabled after the allowance is spent.
   */
  const handleSend = useCallback(() => {
    if (!canSend) return;
    const question = input.trim();
    setInput("");
    void (async () => {
      await sendMessage(question);
      await refreshUser();
    })();
  }, [canSend, input, refreshUser, sendMessage]);

  /**
   * Wipe the conversation, on screen and on the server.
   */
  const handleClear = useCallback(() => {
    void clearHistory();
  }, [clearHistory]);

  /**
   * Keep the newest turn in view.
   *
   * The list is in reading order rather than inverted, so the scroll goes
   * to the end -- which is the newest turn -- every time the content
   * grows. That covers both the first paint of a history that was already
   * there and a turn that arrives while the reader is at the bottom.
   */
  const scrollToNewest = useCallback(() => {
    listRef.current?.scrollToEnd({ animated: false });
  }, []);

  if (repoError) {
    return (
      <View testID="chat-screen" className="flex-1 bg-background">
        <View className="mx-4 mb-3 rounded border border-destructive/30 bg-destructive/10 p-3">
          <Text className="text-xs text-destructive">
            This repository could not be loaded.
          </Text>
        </View>
      </View>
    );
  }

  // Until the repository record resolves there is no UUID to talk to, so
  // the composer is not drawn at all -- otherwise a fast tap sends to
  // ``/api/v1/repository//chat``.
  if (!repo) {
    return (
      <View
        testID="chat-screen"
        className="flex-1 items-center justify-center bg-background"
      >
        <ActivityIndicator color={colors.mutedForeground} />
      </View>
    );
  }

  // The chat endpoint refuses a repository that has not been indexed, so
  // there is nothing to ask about yet. The web app only shows its chat
  // panel for a ready repository; this route is reachable on its own, so
  // the screen says so rather than offering a composer that would fail.
  if (!isReadyStatus(repo.status)) {
    return (
      <View
        testID="chat-screen"
        className="flex-1 items-center justify-center bg-background p-6"
      >
        <Text className="mb-2 text-base font-bold text-foreground">
          Not indexed yet
        </Text>
        <Text className="max-w-[280px] text-center text-[13px] text-muted-foreground">
          This repository is still being indexed. Questions can be asked once it
          is ready.
        </Text>
      </View>
    );
  }

  return (
    <View
      testID="chat-screen"
      // The keyboard height is added here directly rather than through
      // ``KeyboardAvoidingView``, which does not account for the keyboard on
      // Android once edge-to-edge is on. The bottom safe-area inset is added
      // on top: the reported keyboard height stops at the gesture bar, so
      // without it the composer's last few points sit under the keyboard.
      style={{
        paddingBottom: keyboardHeight > 0 ? keyboardHeight + insets.bottom : 0,
      }}
      className="flex-1 bg-background"
    >
      <View className="flex-row items-center justify-between border-b border-border px-4 py-2">
        <Text className="text-sm font-bold text-foreground">
          Chat with Codebase
        </Text>

        {freeChatRemaining !== null ? (
          <Text
            testID="chat-free-remaining"
            className="mr-2 text-[10px] text-muted-foreground"
          >
            {freeChatRemaining} free{" "}
            {freeChatRemaining === 1 ? "question" : "questions"} left
          </Text>
        ) : null}

        {messages.length > 0 ? (
          <Pressable
            testID="chat-clear"
            accessibilityRole="button"
            accessibilityLabel="Clear chat history"
            onPress={handleClear}
            className="min-h-[44px] justify-center rounded px-2 py-1 active:bg-secondary"
          >
            <Text className="text-[11px] font-semibold text-muted-foreground">
              Clear Chat
            </Text>
          </Pressable>
        ) : null}
      </View>

      <FlatList
        ref={listRef}
        testID="chat-list"
        data={messages}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <ChatBubble
            id={item.id}
            question={item.question}
            message={item.answer}
            error={item.error}
            errorKind={item.errorKind}
            url={repo?.github_url ?? ""}
            branch={repo?.ingested_branch ?? null}
            onDelete={deleteMessage}
          />
        )}
        onContentSizeChange={scrollToNewest}
        keyboardShouldPersistTaps="handled"
        className="flex-1"
        contentContainerClassName="p-4"
        ListEmptyComponent={
          isLoadingHistory ? (
            <View
              testID="chat-loading"
              className="items-center justify-center py-16"
            >
              <ActivityIndicator color={colors.mutedForeground} />
            </View>
          ) : (
            <View
              testID="chat-empty"
              className="items-center justify-center py-16"
            >
              <Text className="mb-2 text-[32px] opacity-40">✦</Text>
              <Text className="max-w-[260px] text-center text-[13px] text-muted-foreground">
                Ask questions about the architecture, logic, or ownership.
              </Text>
            </View>
          )
        }
      />

      {quotaExhausted ? (
        <View className="mx-3 mb-2 rounded border border-primary/20 bg-primary/5 px-3 py-2">
          <Text className="text-[11px] text-muted-foreground">
            You&apos;ve used up the free chat questions. Add your own API key to
            keep chatting.
          </Text>
        </View>
      ) : null}

      <View
        className="border-t border-border p-3"
        // The home-indicator inset is only needed while the keyboard is
        // down; with it up, the keyboard's own height already ends the
        // screen.
        style={{ paddingBottom: keyboardHeight > 0 ? 12 : 12 + insets.bottom }}
      >
        <View className="flex-row items-end">
          <TextInput
            testID="chat-input"
            accessibilityLabel="Ask about the codebase"
            value={input}
            onChangeText={setInput}
            placeholder={
              quotaExhausted
                ? "Free chat allowance used up."
                : "Ask about the codebase…"
            }
            placeholderTextColor={colors.mutedForeground}
            editable={!quotaExhausted}
            multiline
            className="max-h-[120px] min-h-[44px] flex-1 rounded border border-input bg-card px-3 py-2 text-[13px] text-foreground"
          />

          <Pressable
            testID="chat-send"
            accessibilityRole="button"
            accessibilityLabel="Send question"
            accessibilityState={{ disabled: !canSend }}
            disabled={!canSend}
            onPress={handleSend}
            className={`ml-2 min-h-[44px] items-center justify-center rounded px-4 ${
              canSend ? "bg-primary" : "bg-secondary"
            }`}
          >
            <Text
              className={`text-[13px] font-semibold ${
                canSend ? "text-primary-foreground" : "text-muted-foreground"
              }`}
            >
              {isLoading ? "Thinking..." : "Send"}
            </Text>
          </Pressable>
        </View>
      </View>
    </View>
  );
}
