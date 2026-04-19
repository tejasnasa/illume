"use client"

import ChatMessage from "@/types/chat";
import { useCallback, useState } from "react";

interface Message {
  id: string;
  question: string;
  answer: ChatMessage | null;
}

export function useChat({ repoId }: { repoId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const sendMessage = useCallback(
    async (question: string) => {
      if (!question.trim() || isLoading) return;

      setIsLoading(true);

      let history: any[] = [];
      const id = crypto.randomUUID();

      setMessages((prev) => {
        history = prev
          .filter((m) => m.answer !== null)
          .map((m) => ({
            question: m.question,
            answer: m.answer!.answer,
          }));

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

        const data: ChatMessage = await res.json();

        setMessages((curr) =>
          curr.map((m) => (m.id === id ? { ...m, answer: data } : m)),
        );
      } catch {
        setMessages((curr) => curr.filter((m) => m.id !== id));
      } finally {
        setIsLoading(false);
      }
    },
    [isLoading, repoId],
  );

  return { messages, isLoading, sendMessage };
}
