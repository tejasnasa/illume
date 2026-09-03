/**
 * Chat state hook with optimistic updates and history persistence.
 * @module UseChat
 */

"use client";

import ChatMessage from "@/types/chat";
import { useCallback, useEffect, useState } from "react";

/**
 * One conversation turn; pending turns have a null answer until resolved.
 */
interface Message {
  id: string;
  question: string;
  answer: ChatMessage | null;
  error?: boolean;
}

/**
 * Manages repository chat: history loading, sending, and deletion.
 *
 * @param repoId - ID of the repository whose chat to manage.
 * @returns Messages, loading flag, and send/delete/clear actions.
 */
export function useChat({ repoId }: { repoId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repoId}/chat/history`,
          {
            credentials: "include",
          },
        );
        if (res.ok) {
          const data = await res.json();
          const mapped = data.map((m: any) => ({
            id: m.id,
            question: m.question,
            answer: {
              answer: m.answer,
              sources: m.sources || [],
            },
          }));
          setMessages(mapped);
        }
      } catch (err) {
        console.error("Failed to fetch chat history", err);
      }
    };
    fetchHistory();
  }, [repoId]);

  /**
   * Sends a question with an optimistic placeholder, then swaps in the answer.
   *
   * Forwards the last answered turns as history so follow-ups stay grounded.
   * @param question - The user's question text.
   */
  const sendMessage = useCallback(
    async (question: string) => {
      if (!question.trim() || isLoading) return;

      setIsLoading(true);

      let history: any[] = [];
      const id = crypto.randomUUID();

      setMessages((prev) => {
        const list: any[] = [];
        prev
          .filter((m) => m.answer !== null && !m.error)
          .forEach((m) => {
            list.push({ role: "user", content: m.question });
            list.push({ role: "assistant", content: m.answer!.answer });
          });
        history = list;

        return [...prev, { id, question, answer: null }];
      });

      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repoId}/chat`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ question, history }),
          },
        );

        if (!res.ok) {
          throw new Error("Failed to get response");
        }

        const data: { id: string; answer: string; sources: any[] } =
          await res.json();

        setMessages((curr) =>
          curr.map((m) =>
            m.id === id
              ? {
                  ...m,
                  id: data.id,
                  answer: {
                    answer: data.answer,
                    sources: data.sources,
                  },
                }
              : m,
          ),
        );
      } catch {
        // Keep the turn visible with an inline error so the user can retry.
        setMessages((curr) =>
          curr.map((m) =>
            m.id === id
              ? {
                  ...m,
                  error: true,
                  answer: {
                    answer: "Failed to get response. Try again.",
                    sources: [],
                  },
                }
              : m,
          ),
        );
      } finally {
        setIsLoading(false);
      }
    },
    [isLoading, repoId],
  );

  /**
   * Removes a message locally and deletes persisted turns server-side.
   *
   * @param messageId - ID of the message to delete.
   */
  const deleteMessage = useCallback(
    async (messageId: string) => {
      const msgToDelete = messages.find((m) => m.id === messageId);

      setMessages((curr) => curr.filter((m) => m.id !== messageId));

      // Optimistic placeholders and error turns were never persisted.
      if (msgToDelete && !msgToDelete.error) {
        try {
          await fetch(
            `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repoId}/chat/${messageId}`,
            {
              method: "DELETE",
              credentials: "include",
            },
          );
        } catch (err) {
          console.error("Failed to delete chat message on server", err);
        }
      }
    },
    [repoId, messages],
  );

  /**
   * Clears all local messages and wipes server-side history.
   */
  const clearHistory = useCallback(async () => {
    setMessages([]);

    try {
      await fetch(
        `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repoId}/chat`,
        {
          method: "DELETE",
          credentials: "include",
        },
      );
    } catch (err) {
      console.error("Failed to clear chat history", err);
    }
  }, [repoId]);

  return { messages, isLoading, sendMessage, deleteMessage, clearHistory };
}
