/**
 * Root error boundary for unexpected runtime failures.
 * @module ErrorPage
 */
"use client";

import StatusScreen, {
  STATUS_GHOST,
  STATUS_PRIMARY,
} from "@/components/ui/StatusScreen";
import Link from "next/link";
import { useEffect } from "react";

/**
 * Fallback UI for an error raised anywhere under the root layout.
 *
 * Every server component in this app signals a failed fetch by throwing, so without
 * this boundary a transient 500 from the backend fell through to the framework's own
 * failure screen -- no navigation, no retry, and nothing distinguishing "the backend
 * is down" from "this page does not exist".
 *
 * @param error - The error that was thrown; `digest` matches it to a server log line.
 * @param unstable_retry - Re-fetches and re-renders the failed segment.
 * @returns Full-page recovery view.
 */
export default function Error({
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
      title="Something went wrong"
      className="min-h-dvh"
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
