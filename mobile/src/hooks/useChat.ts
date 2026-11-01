/**
 * Chat state hook with optimistic updates and history persistence.
 *
 * @module UseChat
 *
 * Port of ``client/src/hooks/useChat.ts``.
 *
 * The behaviour that matters is the one the reader sees:
 *
 * - Sending is **optimistic**. The turn appears immediately with no answer
 *   and is swapped in when the response lands, so the screen never looks
 *   empty while the model is thinking.
 * - A failed turn stays on the screen with an inline error rather than
 *   vanishing, and is marked ``error`` so it is not mistaken for an
 *   answer. An error turn was never persisted, so it is also not sent
 *   back as history.
 * - The free-tier quota gate is a **402** and carries its own wording;
 *   every other failure reads "Failed to get response. Try again."
 * - Deleting a turn and clearing the history are optimistic, and neither
 *   is rolled back when the server call fails.
 *
 * The history itself is server state and comes from React Query, so
 * navigating away and back does not lose it. The turns on screen are
 * local state, because the optimistic ones have no server record yet; the
 * history seeds them once, and the server's copy stays the authority for
 * what was persisted.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import type { default as ChatMessage } from "@/types/chat";
import {
  clearChatHistory,
  deleteChatMessage,
  getChatHistory,
  postChatQuestion,
  type ChatHistoryEntry,
  type ChatHistoryTurn,
} from "@/api/chat";
import { queryKeys } from "@/api/queryKeys";
import { ApiError } from "@/lib/apiError";

/**
 * The failure kinds the hook tells apart.
 *
 * ``generic`` is the catch-all, rendered as the retry string. ``quota`` is
 * the 402 from the free-tier gate, which carries a message of its own and
 * points the reader at their own API key. Separating them lets the screen
 * offer an actionable next step for one specific failure without treating
 * every 5xx as a spent allowance.
 */
export type ChatErrorKind = "generic" | "quota";

/** The message every failure but the quota is rendered with. */
export const GENERIC_ERROR_MESSAGE = "Failed to get response. Try again.";

/**
 * The message the quota failure falls back to.
 *
 * The server sends its own wording with the 402, and that is what the
 * reader normally sees. This copy only shows when the body could not be
 * read.
 */
export const QUOTA_ERROR_MESSAGE =
  "Free chat allowance used up. Add your own API key to keep chatting.";

/**
 * One conversation turn; a pending turn has no answer until it resolves.
 */
export interface ChatTurn {
  /** The turn's id. A pending turn carries a client-side one. */
  id: string;
  /** The question that was asked. */
  question: string;
  /** The answer payload, or ``null`` while the response is pending. */
  answer: ChatMessage | null;
  /** Set when the turn failed; the answer holds the error text. */
  error?: boolean;
  /** Narrows the failure: ``quota`` is the free-tier 402. */
  errorKind?: ChatErrorKind;
}

/** Props for {@link useChat}. */
export interface UseChatProps {
  /**
   * The repository's chat, as its UUID.
   *
   * The chat routes are keyed by the UUID rather than by the user-scoped
   * number the dashboard links on.
   */
  repoId: string;
  /** Whether the history should be fetched at all. */
  enabled?: boolean;
}

/** State and actions returned by {@link useChat}. */
export interface UseChatResult {
  /** The turns on screen, oldest first. */
  messages: ChatTurn[];
  /** True while a question is being answered. */
  isLoading: boolean;
  /** True while the history is being fetched. */
  isLoadingHistory: boolean;
  /** Ask a question; the turn appears before the answer does. */
  sendMessage: (question: string) => Promise<void>;
  /** Remove a turn, locally and on the server. */
  deleteMessage: (messageId: string) => Promise<void>;
  /** Remove every turn, locally and on the server. */
  clearHistory: () => Promise<void>;
}

/**
 * Turn a stored history row into a turn on screen.
 *
 * @param row - The row the history endpoint returned.
 * @returns The turn.
 */
function toTurn(row: ChatHistoryTurn): ChatTurn {
  return {
    id: row.id,
    question: row.question,
    answer: { answer: row.answer, sources: row.sources ?? [] },
  };
}

/**
 * Pull the wording out of a quota failure.
 *
 * The server sends the 402 with a ``detail`` string; that string is what
 * the reader should see. A body that could not be read falls back to the
 * canned copy.
 *
 * @param error - The failure the request raised.
 * @returns The message to show.
 */
function quotaMessage(error: ApiError): string {
  const body = error.body;
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string" && detail.trim().length > 0) {
      return detail;
    }
  }
  return QUOTA_ERROR_MESSAGE;
}

/**
 * Manage the chat of one repository.
 *
 * @param props - The repository's chat id, and whether to fetch at all.
 * @returns The turns, the loading flags and the send/delete/clear actions.
 */
export function useChat({
  repoId,
  enabled = true,
}: UseChatProps): UseChatResult {
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const queryClient = useQueryClient();

  // Counts the client-side ids handed to pending turns. The server's ids
  // are UUIDs, so a pending turn's id must not look like one: the delete
  // route types the id as a UUID and would answer 422 for anything else.
  const localId = useRef(0);

  const history = useQuery({
    queryKey: queryKeys.repositories.chatHistory(repoId),
    queryFn: () => getChatHistory(repoId),
    enabled: enabled && repoId.length > 0,
  });

  // The history seeds the list exactly once. Later refetches are ignored
  // on purpose: the list carries the turns that were sent since the screen
  // opened, and a refetch landing in the middle of a conversation must not
  // reorder or drop them.
  const seeded = useRef(false);

  // A different repository is a different conversation. The flag and the
  // turns on screen belong to the old one, so both are dropped before the
  // new history has a chance to seed them.
  useEffect(() => {
    seeded.current = false;
    setMessages([]);
  }, [repoId]);

  useEffect(() => {
    const rows = history.data;
    if (!rows || seeded.current) return;
    seeded.current = true;
    const stored = rows.map(toTurn);
    setMessages((previous) =>
      previous.length === 0 ? stored : [...stored, ...previous],
    );
  }, [history.data]);

  /**
   * Ask a question and show the turn immediately.
   *
   * @param question - The question text.
   */
  const sendMessage = useCallback(
    async (question: string) => {
      if (!question.trim() || isLoading) return;

      setIsLoading(true);

      localId.current += 1;
      const id = `pending-${localId.current}`;

      // Every prior turn that has an answer and no error. The server
      // truncates what it receives to the last five messages, so the client
      // sends everything and lets the server decide.
      const priorTurns: ChatHistoryEntry[] = messages
        .filter((turn) => turn.answer !== null && !turn.error)
        .flatMap((turn) => [
          { role: "user" as const, content: turn.question },
          {
            role: "assistant" as const,
            content: (turn.answer as ChatMessage).answer,
          },
        ]);

      setMessages((previous) => [...previous, { id, question, answer: null }]);

      try {
        const response = await postChatQuestion(repoId, {
          question,
          history: priorTurns,
        });

        setMessages((current) =>
          current.map((turn) =>
            turn.id === id
              ? {
                  ...turn,
                  id: response.id,
                  answer: {
                    answer: response.answer,
                    sources: response.sources ?? [],
                  },
                }
              : turn,
          ),
        );

        // The turn is persisted now, so the cached history is stale.
        void queryClient.invalidateQueries({
          queryKey: queryKeys.repositories.chatHistory(repoId),
        });
      } catch (error) {
        const isQuota = error instanceof ApiError && error.kind === "quota";
        setMessages((current) =>
          current.map((turn) =>
            turn.id === id
              ? {
                  ...turn,
                  error: true,
                  errorKind: isQuota ? "quota" : "generic",
                  answer: {
                    answer: isQuota
                      ? quotaMessage(error as ApiError)
                      : GENERIC_ERROR_MESSAGE,
                    sources: [],
                  },
                }
              : turn,
          ),
        );
      } finally {
        setIsLoading(false);
      }
    },
    [isLoading, messages, repoId, queryClient],
  );

  /**
   * Remove a turn, locally and on the server.
   *
   * The local removal is not rolled back when the server call fails: the
   * turn is gone from the reader's point of view either way, and putting
   * it back would be more confusing than leaving it.
   *
   * @param messageId - The id of the turn to remove.
   */
  const deleteMessage = useCallback(
    async (messageId: string) => {
      const target = messages.find((turn) => turn.id === messageId);

      setMessages((current) => current.filter((turn) => turn.id !== messageId));

      // An error turn and a pending turn were never persisted, so there is
      // nothing on the server to delete -- and a pending turn's id is not
      // even a UUID the delete route would accept.
      if (!target || target.error || target.answer === null) return;

      try {
        await deleteChatMessage(repoId, messageId);
        void queryClient.invalidateQueries({
          queryKey: queryKeys.repositories.chatHistory(repoId),
        });
      } catch {
        // The turn stays removed on screen; the server keeps a copy.
      }
    },
    [messages, repoId, queryClient],
  );

  /**
   * Remove every turn, locally and on the server.
   */
  const clearHistory = useCallback(async () => {
    setMessages([]);

    try {
      await clearChatHistory(repoId);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.repositories.chatHistory(repoId),
      });
    } catch {
      // The list stays empty on screen; the server keeps its copy.
    }
  }, [repoId, queryClient]);

  return {
    messages,
    isLoading,
    isLoadingHistory: history.isLoading,
    sendMessage,
    deleteMessage,
    clearHistory,
  };
}
