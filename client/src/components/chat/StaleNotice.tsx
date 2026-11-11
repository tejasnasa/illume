/**
 * The "May be out of date" badge under an answer whose cited files have changed.
 * @module StaleNotice
 */
"use client";

import {
  ArrowSquareOutIcon,
  CaretDownIcon,
  ClockCounterClockwiseIcon,
} from "@phosphor-icons/react";
import { useState } from "react";

/** What the server knows about a stale answer, read from the chat history. */
export interface StaleInfo {
  /** The cited files that changed since the answer was given. */
  paths: string[];
}

interface ChangedCommit {
  hash: string;
  message: string;
  author_name: string;
  authored_at: string;
  files: string[];
}

interface Changes {
  stale_paths: string[];
  commits: ChangedCommit[];
  compare_url: string | null;
}

const BACKEND = () => process.env.NEXT_PUBLIC_BACKEND_URL;

type Load =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; changes: Changes };

/**
 * A badge that opens to what changed under an answer, with a way to ask again.
 *
 * The changes are fetched the first time the badge is opened, and kept.
 *
 * @param repoId - Repository id.
 * @param messageId - The stored chat message the answer belongs to.
 * @param stale - What the history already says about the change.
 * @param onReask - Sends the same question again as a new turn; omitted while a run is live.
 * @returns The badge and its panel.
 */
export default function StaleNotice({
  repoId,
  messageId,
  stale,
  onReask,
}: {
  repoId: string;
  messageId: string;
  stale: StaleInfo;
  onReask?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [load, setLoad] = useState<Load>({ status: "idle" });

  const fetchChanges = async () => {
    setLoad({ status: "loading" });
    try {
      const res = await fetch(
        `${BACKEND()}/api/v1/repository/${repoId}/chat/${messageId}/changes`,
        { credentials: "include" },
      );
      if (!res.ok) throw new Error(`changes ${res.status}`);
      setLoad({ status: "ready", changes: (await res.json()) as Changes });
    } catch {
      setLoad({ status: "error" });
    }
  };

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && load.status === "idle") void fetchChanges();
  };

  return (
    <div className="text-xs" data-testid="stale-notice">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-expanded={open}
          onClick={toggle}
          className="inline-flex items-center gap-1.5 rounded-full border border-yellow-400/30 bg-yellow-400/5 px-2.5 py-1 font-medium text-yellow-300 hover:bg-yellow-400/10 cursor-pointer"
        >
          <ClockCounterClockwiseIcon size={13} weight="bold" />
          May be out of date
          <CaretDownIcon
            size={11}
            weight="bold"
            className={open ? "rotate-180" : ""}
          />
        </button>
        {onReask && (
          <button
            type="button"
            onClick={onReask}
            className="rounded-full border border-(--border) px-2.5 py-1 font-medium text-(--foreground) hover:bg-(--secondary)/50 cursor-pointer"
          >
            Re-ask
          </button>
        )}
      </div>

      {open && (
        <div
          className="mt-2 space-y-2 rounded-lg border border-(--border) bg-(--secondary)/20 p-3"
          data-testid="stale-panel"
        >
          <p className="text-(--muted-foreground)">
            Files this answer cited have changed since it was given.
          </p>

          <ul className="space-y-0.5 font-mono text-[11px] text-(--foreground)">
            {(load.status === "ready"
              ? load.changes.stale_paths
              : stale.paths
            ).map((path) => (
              <li key={path} className="break-all">
                {path}
              </li>
            ))}
          </ul>

          {load.status === "loading" && (
            <p className="text-(--muted-foreground)" role="status">
              Loading changes…
            </p>
          )}
          {load.status === "error" && (
            <p className="text-red-400" role="alert">
              Could not load the changes.{" "}
              <button
                type="button"
                onClick={() => void fetchChanges()}
                className="underline underline-offset-2 cursor-pointer"
              >
                Try again
              </button>
            </p>
          )}
          {load.status === "ready" && (
            <>
              {load.changes.commits.length > 0 && (
                <ul className="space-y-1.5" data-testid="stale-commits">
                  {load.changes.commits.map((commit) => (
                    <li key={commit.hash} className="leading-snug">
                      <span className="font-mono text-(--muted-foreground)">
                        {commit.hash.slice(0, 7)}
                      </span>{" "}
                      <span className="text-(--foreground)">
                        {commit.message.split("\n")[0]}
                      </span>
                      <span className="block text-[11px] text-(--muted-foreground)">
                        {commit.author_name} · {commit.authored_at.slice(0, 10)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {load.changes.commits.length === 0 && (
                <p className="text-(--muted-foreground)">
                  No mined commits are listed for these files yet.
                </p>
              )}
              {load.changes.compare_url && (
                <a
                  href={load.changes.compare_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-(--primary) underline-offset-2 hover:underline"
                >
                  Compare on GitHub
                  <ArrowSquareOutIcon size={12} />
                </a>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
