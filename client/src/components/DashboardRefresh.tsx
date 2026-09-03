/**
 * Client-side poller that refreshes the dashboard while repos ingest.
 * @module DashboardRefresh
 */
"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Repository from "@/types/repository";

/**
 * Triggers a server refresh every 5s until all repositories settle.
 *
 * @param repositories - Dashboard repository list with ingestion statuses.
 * @returns Null; only side-effects via router refresh.
 */
export default function DashboardRefresh({ repositories }: { repositories: Repository[] }) {
  const router = useRouter();

  /** Polls while any repo is neither ready nor failed. */
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
