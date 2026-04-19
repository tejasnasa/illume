import Glossary from "@/types/glossary";
import { headers } from "next/headers";

export async function GetGlossary(
  id: string,
  page: number,
  page_size: number,
): Promise<Glossary> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${id}/glossary?page=${page}&page_size=${page_size}`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch repo glossary");

  const data = await res.json();

  return data;
}

export async function GetGlossarySearchResults(
  id: string,
  q: string,
): Promise<Glossary> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${id}/glossary?q=${encodeURIComponent(q)}`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch repo glossary");

  const data = await res.json();

  return data;
}
