/**
 * The "May be out of date" badge under an answer whose cited files changed.
 *
 * @module StaleNotice
 *
 * Port of ``client/src/components/chat/StaleNotice.tsx``. The changes are
 * fetched the first time the badge is opened, and kept.
 */

import { useState } from "react";
import { Linking, Pressable, Text, View } from "react-native";

import {
  getAnswerChanges,
  type AnswerChanges,
  type StaleInfo,
} from "@/api/conversations";

type Load =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; changes: AnswerChanges };

/**
 * A badge that opens to what changed under an answer, with a way to ask again.
 *
 * @param props - Repository, stored message, what the history says, and the re-ask action.
 * @returns The badge and its panel.
 */
export function StaleNotice({
  repoId,
  messageId,
  stale,
  onReask,
}: {
  repoId: string;
  messageId: string;
  stale: StaleInfo;
  onReask?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [load, setLoad] = useState<Load>({ status: "idle" });

  const fetchChanges = async () => {
    setLoad({ status: "loading" });
    try {
      setLoad({
        status: "ready",
        changes: await getAnswerChanges(repoId, messageId),
      });
    } catch {
      setLoad({ status: "error" });
    }
  };

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && load.status === "idle") void fetchChanges();
  };

  const paths =
    load.status === "ready" ? load.changes.stale_paths : stale.paths;

  return (
    <View testID="stale-notice" className="rounded-sm border border-warning/30 bg-warning/5">
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        onPress={toggle}
        className="min-h-[40px] flex-row items-center gap-2 px-3"
      >
        <Text className="font-pixel text-[11px] uppercase tracking-[1px] text-warning">
          May be out of date
        </Text>
        <Text className="font-pixel text-[11px] text-muted-foreground">
          {paths.length} {paths.length === 1 ? "file" : "files"} changed
        </Text>
      </Pressable>
      {open ? (
        <View className="gap-2 px-3 pb-3">
          {load.status === "loading" ? (
            <Text className="text-xs text-muted-foreground">Loading changes…</Text>
          ) : null}
          {load.status === "error" ? (
            <Text className="text-xs text-destructive">
              The changes could not be loaded.
            </Text>
          ) : null}
          {paths.slice(0, 10).map((path) => (
            <Text
              key={path}
              numberOfLines={1}
              className="font-pixel text-[11px] text-foreground/85"
            >
              {path}
            </Text>
          ))}
          {load.status === "ready"
            ? load.changes.commits.slice(0, 8).map((commit) => (
                <Text key={commit.hash} className="text-xs text-muted-foreground">
                  <Text className="font-pixel text-chart-1">
                    {commit.hash.slice(0, 7)}
                  </Text>{" "}
                  {commit.message.split("\n")[0]} · {commit.author_name}
                </Text>
              ))
            : null}
          <View className="flex-row gap-4">
            {onReask ? (
              <Pressable
                accessibilityRole="button"
                onPress={onReask}
                className="min-h-[36px] justify-center"
              >
                <Text className="font-pixel text-xs uppercase text-accent">
                  Ask again
                </Text>
              </Pressable>
            ) : null}
            {load.status === "ready" && load.changes.compare_url ? (
              <Pressable
                accessibilityRole="link"
                onPress={() =>
                  void Linking.openURL(
                    (load as { changes: AnswerChanges }).changes
                      .compare_url as string,
                  )
                }
                className="min-h-[36px] justify-center"
              >
                <Text className="font-pixel text-xs uppercase text-muted-foreground">
                  View on GitHub
                </Text>
              </Pressable>
            ) : null}
          </View>
        </View>
      ) : null}
    </View>
  );
}
