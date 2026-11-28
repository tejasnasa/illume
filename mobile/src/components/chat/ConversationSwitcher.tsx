/**
 * The list of a repository's conversations, in a sheet.
 *
 * @module ConversationSwitcher
 *
 * Port of ``client/src/components/chat/ConversationSidebar.tsx``: open a
 * conversation, start a new one, rename one inline, or delete one after a
 * confirmation. On the phone it is a bottom sheet rather than a sidebar.
 */

import { useState } from "react";
import {
  Alert,
  Modal,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { MAX_TITLE_CHARS } from "@/hooks/useConversationList";
import { timeAgo } from "@/lib/timeAgo";
import { colors } from "@/theme/tokens";
import type { ConversationSummary } from "@/types/conversation";

/** The title shown for a conversation that has none yet. */
export function displayTitle(item: ConversationSummary): string {
  return item.title?.trim() || "New conversation";
}

/**
 * Renders the switcher sheet.
 *
 * @param props - Visibility, the list, the open conversation and the handlers.
 * @returns The sheet.
 */
export function ConversationSwitcher({
  open,
  items,
  activeId,
  loaded,
  onClose,
  onOpen,
  onNew,
  onRename,
  onDelete,
}: {
  open: boolean;
  items: ConversationSummary[];
  activeId: string | null;
  loaded: boolean;
  onClose: () => void;
  onOpen: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => Promise<boolean>;
  onDelete: (id: string) => void;
}) {
  const insets = useSafeAreaInsets();
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const confirmDelete = (item: ConversationSummary) => {
    Alert.alert(
      "Delete conversation",
      `"${displayTitle(item)}" and its ${item.message_count} messages will be removed.`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Delete", style: "destructive", onPress: () => onDelete(item.id) },
      ],
    );
  };

  const commitRename = async (id: string) => {
    const ok = await onRename(id, draft);
    if (ok) setEditing(null);
  };

  return (
    <Modal visible={open} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable className="flex-1 justify-end bg-black/60" onPress={onClose}>
        <Pressable
          onPress={() => {}}
          className="max-h-[80%] rounded-t-md border border-border bg-popover"
          style={{ paddingBottom: insets.bottom + 8 }}
        >
          <View className="flex-row items-center justify-between px-4 pb-2 pt-4">
            <Text className="font-pixel text-xs uppercase tracking-[1.2px] text-muted-foreground">
              Conversations
            </Text>
            <Pressable
              testID="conversation-new"
              accessibilityRole="button"
              onPress={() => {
                onNew();
                onClose();
              }}
              className="min-h-[36px] justify-center rounded-sm border border-input px-3"
            >
              <Text className="font-pixel text-[11px] uppercase text-zinc-300">
                New chat
              </Text>
            </Pressable>
          </View>
          <ScrollView>
            {loaded && items.length === 0 ? (
              <Text className="px-4 py-6 text-sm text-muted-foreground">
                No conversations yet. Ask a question to start one.
              </Text>
            ) : null}
            {items.map((item) => {
              const active = item.id === activeId;
              return (
                <View
                  key={item.id}
                  testID={`conversation-${item.id}`}
                  className={`border-b border-border px-4 py-2.5 ${active ? "bg-white/5" : ""}`}
                >
                  {editing === item.id ? (
                    <View className="flex-row items-center gap-2">
                      <TextInput
                        testID="conversation-rename-input"
                        value={draft}
                        onChangeText={setDraft}
                        maxLength={MAX_TITLE_CHARS}
                        autoFocus
                        onSubmitEditing={() => void commitRename(item.id)}
                        placeholderTextColor={colors.mutedForeground}
                        className="min-h-[40px] flex-1 rounded-sm border border-input px-2 text-sm text-foreground"
                      />
                      <Pressable
                        testID="conversation-rename-save"
                        onPress={() => void commitRename(item.id)}
                        className="min-h-[40px] justify-center px-2"
                      >
                        <Text className="font-pixel text-xs uppercase text-accent">
                          Save
                        </Text>
                      </Pressable>
                      <Pressable
                        onPress={() => setEditing(null)}
                        className="min-h-[40px] justify-center px-2"
                      >
                        <Text className="font-pixel text-xs uppercase text-muted-foreground">
                          Cancel
                        </Text>
                      </Pressable>
                    </View>
                  ) : (
                    <>
                      <Pressable
                        accessibilityRole="button"
                        onPress={() => {
                          onOpen(item.id);
                          onClose();
                        }}
                        className="min-h-[40px] justify-center"
                      >
                        <Text numberOfLines={1} className="text-[14px] text-foreground">
                          {displayTitle(item)}
                        </Text>
                        <Text className="text-xs text-muted-foreground">
                          {item.message_count}{" "}
                          {item.message_count === 1 ? "message" : "messages"} ·{" "}
                          {timeAgo(item.updated_at)}
                        </Text>
                      </Pressable>
                      <View className="flex-row gap-4">
                        <Pressable
                          testID={`conversation-rename-${item.id}`}
                          onPress={() => {
                            setEditing(item.id);
                            setDraft(displayTitle(item));
                          }}
                          className="min-h-[36px] justify-center"
                        >
                          <Text className="font-pixel text-[11px] uppercase text-muted-foreground">
                            Rename
                          </Text>
                        </Pressable>
                        <Pressable
                          testID={`conversation-delete-${item.id}`}
                          onPress={() => confirmDelete(item)}
                          className="min-h-[36px] justify-center"
                        >
                          <Text className="font-pixel text-[11px] uppercase text-destructive">
                            Delete
                          </Text>
                        </Pressable>
                      </View>
                    </>
                  )}
                </View>
              );
            })}
          </ScrollView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
