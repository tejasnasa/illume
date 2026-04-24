"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Repository from "@/types/repository";

export default function DashboardRefresh({ repositories }: { repositories: Repository[] }) {
  const router = useRouter();

  useEffect(() => {
    const hasPending = repositories.some(r =>
      r.status !== "ready" && r.status !== "failed"
    );

    if (hasPending) {
      const interval = setInterval(() => {
        router.refresh();
      }, 5000);

      return () => clearInterval(interval);
    }
  }, [repositories, router]);

  return null;
}
