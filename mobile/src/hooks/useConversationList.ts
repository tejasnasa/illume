/**
 * A repository's list of chat conversations, with rename and delete.
 *
 * @module UseConversationList
 *
 * Port of ``client/src/hooks/useConversationList.ts``.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  deleteConversation,
  listConversations,
  renameConversation,
} from "@/api/conversations";
import { ApiError } from "@/lib/apiError";
import type { ConversationSummary } from "@/types/conversation";

/** The longest title a conversation may be renamed to. */
export const MAX_TITLE_CHARS = 120;

/**
 * Loads the conversations and keeps them current.
 *
 * Rename and delete are optimistic and are put back when the server refuses.
 * `refresh` re-reads the list, which is how a finished turn's new title and
 * position arrive.
 *
 * @param repoId - Repository UUID; empty until the repository has loaded.
 * @returns The list, a loading flag and the actions the switcher offers.
 */
export function useConversationList(repoId: string) {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const itemsRef = useRef(items);
  itemsRef.current = items;

  const refresh = useCallback(async () => {
    if (!repoId) return;
    try {
      setItems(await listConversations(repoId));
    } catch {
      // The list is a convenience; the chat itself still works without it.
    } finally {
      setLoaded(true);
    }
  }, [repoId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  /** Renames a conversation; blank or over-long titles are not sent. */
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
        await renameConversation(repoId, id, next);
        return true;
      } catch {
        setItems(previous);
        return false;
      }
    },
    [repoId],
  );

  /** Deletes a conversation and its turns; a 404 counts as deleted. */
  const remove = useCallback(
    async (id: string) => {
      const previous = itemsRef.current;
      setItems((current) => current.filter((item) => item.id !== id));
      try {
        await deleteConversation(repoId, id);
        return true;
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return true;
        setItems(previous);
        return false;
      }
    },
    [repoId],
  );

  return { items, loaded, refresh, rename, remove };
}
