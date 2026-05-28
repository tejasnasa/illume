"use client";

import ChatMessage from "@/types/chat";
import { useCallback, useEffect, useState } from "react";

interface Message {
  id: string;
  question: string;
  answer: ChatMessage | null;
  error?: boolean;
}

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

  const deleteMessage = useCallback(
    async (messageId: string) => {
      const msgToDelete = messages.find((m) => m.id === messageId);

      setMessages((curr) => curr.filter((m) => m.id !== messageId));

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
