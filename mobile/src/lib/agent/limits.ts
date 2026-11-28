/**
 * Input size limits the server enforces on a question and its history.
 * @module AgentLimits
 */
import type { HistoryMessage } from "@/hooks/useAgentStream";

/** The longest question the server accepts, in characters. */
export const MAX_QUESTION_CHARS = 4000;

/** The most prior turns one request may carry. */
export const MAX_HISTORY_ITEMS = 40;

/** The longest single prior turn one request may carry, in characters. */
export const MAX_HISTORY_CONTENT_CHARS = 20000;

/**
 * Fits a history to what the server accepts: the newest turns that fit the
 * item limit, each cut to the length limit.
 *
 * @param history - Prior turns, oldest first.
 * @returns A history the server will not refuse for its size.
 */
export function boundHistory(history: HistoryMessage[]): HistoryMessage[] {
  return history
    .slice(-MAX_HISTORY_ITEMS)
    .map((message) =>
      message.content.length > MAX_HISTORY_CONTENT_CHARS
        ? {
            ...message,
            content: message.content.slice(0, MAX_HISTORY_CONTENT_CHARS),
          }
        : message,
    );
}
