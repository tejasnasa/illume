/**
 * Chat fetch for repository Q&A history.
 * @module ChatApi
 */

import ChatMessage from "@/types/chat";
import { headers } from "next/headers";

/**
 * Fetches the chat payload for a repository.
 *
 * @param id - User-scoped repository number.
 * @returns The chat message with answer and source citations.
 * @throws Error if the fetch fails.
 */
export async function GetChat(id: number): Promise<ChatMessage> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${id}/chat`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch chat message");

  const data = await res.json();

  return data;
}
