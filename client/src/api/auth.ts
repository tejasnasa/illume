import User from "@/types/user";
import { headers } from "next/headers";

export default async function GetMyData(): Promise<User> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/auth/me`,
    {
      headers: { cookie: (await headers()).get("cookie") ?? "" },
      cache: "no-store",
    },
  );

  if (!res.ok) throw new Error("Failed to fetch my data");

  const data = await res.json();

  console.log(data)

  return data;
}
