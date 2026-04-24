"use server";
import Ownership, { Silo } from "@/types/ownership";
import { headers } from "next/headers";

export async function GetOwnership(
  id: string,
  page: number,
  page_size: number,
  filePath?: string,
): Promise<Ownership> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${id}/ownership?page=${page}&page_size=${page_size}${filePath ? `&file_path=${encodeURIComponent(filePath)}` : ""}`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch repo ownership");

  const data = await res.json();

  return data;
}

export async function GetOwnershipSilos(
  id: string,
  page: number,
  page_size: number,
): Promise<Silo> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${id}/ownership/silos?page=${page}&page_size=${page_size}`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch repo ownership");

  const data = await res.json();

  return data;
}