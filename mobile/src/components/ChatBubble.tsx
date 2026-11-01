/**
 * Chat message bubble pairing a user question with its AI answer.
 *
 * @module ChatBubble
 *
 * Port of ``client/src/components/ui/ChatBubble.tsx``.
 *
 * The web bubble renders the answer through ``react-markdown``; here the
 * answer is parsed into blocks by :func:`parseMarkdownBlocks` and drawn
 * with plain React Native text. The shapes are the same -- the question on
 * the right, the answer on the left, the citations underneath -- so a
 * reader coming from the web recognises the screen.
 *
 * Two things are deliberately different:
 *
 * - The delete control is a labelled button under the answer rather than
 *   an icon in the corner. The web reveals it on hover, which a phone has
 *   no way to do, and an always-visible icon in the corner would sit on
 *   top of the first line of the answer.
 * - The free-tier failure links to the app's own settings route.
 */

import { useMemo } from "react";
import { Linking, Platform, Pressable, Text, View } from "react-native";
import { router } from "expo-router";

import type { default as ChatMessage } from "@/types/chat";
import type { ChatErrorKind } from "@/hooks/useChat";
import { parseMarkdownBlocks, type MarkdownRun } from "@/lib/markdownBlocks";
import { CitationCard } from "@/components/CitationCard";
import { colors } from "@/theme/tokens";

/** The monospace face used for code spans and code blocks. */
const MONOSPACE = Platform.select({
  ios: "Menlo",
  android: "monospace",
  default: "monospace",
});

/**
 * Draw the inline runs of a block.
 *
 * A run is a piece of text with at most one style: bold, italic, code, or
 * a link. The runs are nested inside the text element of their block, so
 * they inherit its size and colour.
 *
 * @param props - The runs to draw.
 * @returns The drawn runs.
 */
function InlineRuns({ runs }: { runs: MarkdownRun }) {
  return (
    <>
      {runs.map((run, index) => {
        const href = run.href;
        return (
          <Text
            key={`${index}-${run.text.slice(0, 12)}`}
            style={
              run.code
                ? { fontFamily: MONOSPACE, color: colors.chart1 }
                : run.bold
                  ? { fontWeight: "bold" }
                  : run.italic
                    ? { fontStyle: "italic" }
                    : undefined
            }
            onPress={href ? () => void Linking.openURL(href) : undefined}
          >
            {run.text}
          </Text>
        );
      })}
    </>
  );
}

/**
 * Draw an answer as its markdown blocks.
 *
 * @param props - The markdown source of the answer.
 * @returns The drawn blocks.
 */
function MarkdownAnswer({ source }: { source: string }) {
  const blocks = useMemo(() => parseMarkdownBlocks(source), [source]);

  return (
    <View testID="chat-answer-markdown">
      {blocks.map((block, index) => {
        if (block.type === "heading") {
          return (
            <Text
              key={index}
              className={`mb-1 mt-2 font-bold text-foreground ${
                block.level <= 2 ? "text-[15px]" : "text-[14px]"
              }`}
            >
              <InlineRuns runs={block.runs} />
            </Text>
          );
        }

        if (block.type === "list") {
          return (
            <View key={index} className="mb-2">
              {block.items.map((item, itemIndex) => (
                <View key={itemIndex} className="mb-1 flex-row">
                  <Text className="mr-2 w-5 text-[13px] leading-[19px] text-muted-foreground">
                    {block.ordered ? `${itemIndex + 1}.` : "•"}
                  </Text>
                  <Text className="flex-1 text-[13px] leading-[19px] text-foreground">
                    <InlineRuns runs={item} />
                  </Text>
                </View>
              ))}
            </View>
          );
        }

        if (block.type === "code") {
          return (
            <View
              key={index}
              className="mb-2 rounded border border-border bg-secondary/40 p-2"
            >
              {block.language ? (
                <Text className="mb-1 text-[9px] uppercase tracking-wider text-muted-foreground">
                  {block.language}
                </Text>
              ) : null}
              <Text
                style={{ fontFamily: MONOSPACE }}
                className="text-[11px] leading-[15px] text-foreground"
              >
                {block.code}
              </Text>
            </View>
          );
        }

        return (
          <Text
            key={index}
            className="mb-2 text-[13px] leading-[19px] text-foreground"
          >
            <InlineRuns runs={block.runs} />
          </Text>
        );
      })}
    </View>
  );
}

/** Props for the {@link ChatBubble} component. */
export interface ChatBubbleProps {
  /** The turn's id; handed to ``onDelete``. */
  id: string;
  /** The question that was asked. */
  question: string;
  /** The answer payload, or ``null`` while the response is pending. */
  message: ChatMessage | null;
  /** Whether the turn failed; the answer then holds the error text. */
  error?: boolean;
  /**
   * Narrows the failure. ``quota`` is the free-tier 402, which gets a
   * pointer to the settings screen instead of the generic retry string.
   */
  errorKind?: ChatErrorKind;
  /** The repository's GitHub URL; the citation links are built from it. */
  url: string;
  /** The commit the repository was ingested at; the preferred link ref. */
  commitSha?: string | null;
  /** The branch the repository was ingested from; the fallback link ref. */
  branch?: string | null;
  /** Called when the reader deletes the turn. */
  onDelete?: (id: string) => void;
}

/**
 * Draw one conversation turn.
 *
 * @param props - The turn's question, answer, failure and citations.
 * @returns The rendered bubble.
 */
export function ChatBubble({
  id,
  question,
  message,
  error,
  errorKind,
  url,
  commitSha,
  branch,
  onDelete,
}: ChatBubbleProps) {
  return (
    <View testID="chat-bubble" className="mb-4">
      <View className="mb-2 items-end">
        <View className="max-w-[85%] rounded-2xl rounded-tr-sm border border-border bg-card px-3 py-2">
          <Text className="text-[13px] leading-[19px] text-card-foreground">
            {question}
          </Text>
        </View>
      </View>

      {message === null ? (
        <View
          testID="chat-bubble-pending"
          className="flex-row items-center rounded-2xl rounded-tl-sm border border-border bg-card px-3 py-2"
        >
          <Text className="text-[13px] font-medium text-primary">
            Analyzing codebase...
          </Text>
        </View>
      ) : (
        <View
          testID="chat-bubble-answer"
          className={`rounded-2xl rounded-tl-sm border p-3 ${
            error
              ? "border-destructive/30 bg-destructive/10"
              : "border-border bg-card"
          }`}
        >
          {errorKind === "quota" ? (
            <View testID="chat-bubble-error">
              <Text className="text-[13px] leading-[19px] text-destructive">
                {message.answer}
              </Text>
              <Text className="mt-1 text-[13px] leading-[19px] text-muted-foreground">
                <Text
                  className="text-primary"
                  onPress={() => router.push("/(app)/settings")}
                >
                  Add your own API key
                </Text>{" "}
                to keep chatting.
              </Text>
            </View>
          ) : error ? (
            <Text
              testID="chat-bubble-error"
              className="text-[13px] leading-[19px] font-medium text-destructive"
            >
              {message.answer}
            </Text>
          ) : (
            <MarkdownAnswer source={message.answer} />
          )}

          {message.sources.length > 0 ? (
            <View className="mt-3 border-t border-border pt-3">
              <Text className="mb-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                Sources Cited ({message.sources.length})
              </Text>
              {message.sources.map((source, index) => (
                <CitationCard
                  key={`${source.source_type}-${index}`}
                  src={source}
                  url={url}
                  commitSha={commitSha}
                  branch={branch}
                  testID={`citation-card-${index}`}
                />
              ))}
            </View>
          ) : null}

          {onDelete ? (
            <View className="mt-2 flex-row justify-end">
              <Pressable
                testID="chat-bubble-delete"
                accessibilityRole="button"
                accessibilityLabel="Delete message"
                onPress={() => onDelete(id)}
                hitSlop={8}
                className="rounded px-2 py-1 active:bg-secondary"
              >
                <Text className="text-[11px] text-muted-foreground">
                  Delete
                </Text>
              </Pressable>
            </View>
          ) : null}
        </View>
      )}
    </View>
  );
}

export default ChatBubble;
