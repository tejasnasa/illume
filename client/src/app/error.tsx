/**
 * Root error boundary for unexpected runtime failures.
 * @module ErrorPage
 */
"use client";

import {
  ArrowsClockwiseIcon,
  HouseIcon,
  WarningDiamondIcon,
} from "@phosphor-icons/react/dist/ssr";
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
    <main className="min-h-screen flex items-center justify-center p-6">
      <div className="glass-card rounded-sm border border-(--destructive)/30 p-8 max-w-md w-full flex flex-col items-center gap-5 text-center">
        <WarningDiamondIcon size={48} className="text-(--destructive)" />

        <div className="flex flex-col gap-2">
          <h1 className="text-xl font-bold text-(--foreground)">
            Something went wrong
          </h1>
          <p className="text-sm text-(--muted-foreground) leading-relaxed">
            This page could not be loaded. Please retry later.
          </p>
        </div>

        {/* In production the framework replaces a server error's message with a
            generic one, so the digest is the only handle on the real cause. */}
        {error.digest && (
          <p className="font-mono text-xs text-(--muted-foreground)/60 break-all">
            Reference: {error.digest}
          </p>
        )}

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => unstable_retry()}
            className="flex items-center gap-2 px-4 py-2 bg-(--primary)/10 hover:bg-(--primary)/20 border border-(--primary)/30 text-(--primary) text-sm font-semibold rounded-sm transition-colors"
          >
            <ArrowsClockwiseIcon size={16} />
            Try Again
          </button>
          <Link
            href="/dashboard"
            className="flex items-center gap-2 px-4 py-2 border border-(--border) hover:bg-(--secondary) text-sm font-semibold rounded-sm transition-colors text-(--muted-foreground)"
          >
            <HouseIcon size={16} />
            Dashboard
          </Link>
        </div>
      </div>
    </main>
  );
}
