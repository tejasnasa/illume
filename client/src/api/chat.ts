import ChatMessage from "@/types/chat";
import { headers } from "next/headers";

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