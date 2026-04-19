import Guide from "@/types/guide";
import { headers } from "next/headers";

export async function GetGuide(id: string): Promise<Guide> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${id}/guide`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch repo guide");

  const data = await res.json();

  return data;
}
