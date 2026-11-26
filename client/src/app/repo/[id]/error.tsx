/**
 * Error boundary for the repository routes.
 * @module RepoErrorPage
 */
"use client";

import StatusScreen, {
  STATUS_GHOST,
  STATUS_PRIMARY,
} from "@/components/ui/StatusScreen";
import Link from "next/link";
import { useEffect } from "react";

/**
 * Fallback UI for an error raised inside a repository route.
 *
 * Nested under the root boundary so the message can be about a repository rather than
 * about the app. Errors thrown by `repo/[id]/layout.tsx` itself are caught by the root
 * boundary instead -- an `error.tsx` wraps the pages and nested layouts of its segment,
 * not the layout it sits beside.
 *
 * @param error - The error that was thrown; `digest` matches it to a server log line.
 * @param unstable_retry - Re-fetches and re-renders the failed segment.
 * @returns Recovery view with a way back to the dashboard.
 */
export default function RepoError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <StatusScreen
      command="illume retry"
      code="500"
      title="Could not load this repository"
      className="min-h-[calc(100dvh-106px)] md:min-h-[calc(100dvh-65px)]"
      actions={
        <>
          <button
            type="button"
            onClick={() => unstable_retry()}
            className={STATUS_PRIMARY}
          >
            <span aria-hidden="true">↻</span> Try again
          </button>
          <Link href="/dashboard" className={STATUS_GHOST}>
            Dashboard
          </Link>
        </>
      }
      // In production the framework replaces a server error's message with a
      // generic one, so the digest is the only handle on the real cause.
      footnote={error.digest ? `Reference: ${error.digest}` : undefined}
    >
      <p className="m-0">This page could not be loaded. The server may be restarting; trying again in a moment usually works.</p>
    </StatusScreen>
  );
}
