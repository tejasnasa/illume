/**
 * A repository's list of chat conversations, with rename and delete.
 * @module UseConversationList
 */
"use client";

import type { ConversationSummary } from "@/types/conversation";
import { useCallback, useEffect, useRef, useState } from "react";

const BACKEND = () => process.env.NEXT_PUBLIC_BACKEND_URL;

/** The longest title a conversation may be renamed to. */
export const MAX_TITLE_CHARS = 120;

/**
 * Loads the conversations and keeps them current.
 *
 * Rename and delete are optimistic and are put back when the server refuses.
 * `refresh` re-reads the list, which is how a finished turn's new title and
 * position arrive.
 *
 * @param repoId - Repository id.
 * @returns The list, a loading flag and the actions the sidebar offers.
 */
export function useConversationList(repoId: string) {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const base = `${BACKEND()}/api/v1/repository/${repoId}/conversations`;

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(base, { credentials: "include" });
      if (!res.ok) return;
      setItems((await res.json()) as ConversationSummary[]);
    } catch (error) {
      console.error("Failed to fetch conversations", error);
    } finally {
      setLoaded(true);
    }
  }, [base]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  /**
   * Renames a conversation.
   *
   * @param id - The conversation.
   * @param title - The new title; blank or over-long titles are not sent.
   * @returns Whether the rename was accepted.
   */
  const rename = useCallback(
    async (id: string, title: string) => {
      const next = title.trim();
      if (!next || next.length > MAX_TITLE_CHARS) return false;
      const previous = itemsRef.current;
      setItems((current) =>
        current.map((item) =>
          item.id === id ? { ...item, title: next } : item,
        ),
      );
      try {
        const res = await fetch(`${base}/${id}`, {
          method: "PATCH",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: next }),
        });
        if (!res.ok) throw new Error(String(res.status));
        return true;
      } catch (error) {
        console.error("Failed to rename conversation", error);
        setItems(previous);
        return false;
      }
    },
    [base],
  );

  /**
   * Deletes a conversation and its turns.
   *
   * @param id - The conversation.
   * @returns Whether the server deleted it.
   */
  const remove = useCallback(
    async (id: string) => {
      const previous = itemsRef.current;
      setItems((current) => current.filter((item) => item.id !== id));
      try {
        const res = await fetch(`${base}/${id}`, {
          method: "DELETE",
          credentials: "include",
        });
        if (!res.ok && res.status !== 404) throw new Error(String(res.status));
        return true;
      } catch (error) {
        console.error("Failed to delete conversation", error);
        setItems(previous);
        return false;
      }
    },
    [base],
  );

  return { items, loaded, refresh, rename, remove };
}
