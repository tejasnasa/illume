/**
 * A one-line service status read from the backend's health probe.
 * @module SystemStatus
 */
"use client";

import { useEffect, useState } from "react";

type Status = "checking" | "ok" | "degraded" | "down";

/** What each status says, and the colour of its light. */
const COPY: Record<Status, { label: string; color: string }> = {
  checking: { label: "Checking status", color: "var(--faint-foreground)" },
  ok: { label: "All systems normal", color: "var(--success)" },
  degraded: { label: "Partial outage", color: "#facc15" },
  down: { label: "Service unreachable", color: "var(--destructive)" },
};

/**
 * Asks `/healthz` once on mount and shows what it answered. A 503 means a
 * dependency is down while the API still answers; no answer at all means the
 * API itself is unreachable.
 *
 * @returns The status line.
 */
export default function SystemStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/healthz`, {
      cache: "no-store",
      signal: controller.signal,
    })
      .then((res) => setStatus(res.ok ? "ok" : "degraded"))
      .catch(() => {
        if (!controller.signal.aborted) setStatus("down");
      });
    return () => controller.abort();
  }, []);

  const { label, color } = COPY[status];
  return (
    <span
      role="status"
      className="inline-flex items-center gap-2 font-pixel text-[11px] tracking-[0.12em] text-(--muted-foreground) uppercase"
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 ${status === "ok" ? "blink" : ""}`}
        style={{ background: color }}
      />
      {label}
    </span>
  );
}
