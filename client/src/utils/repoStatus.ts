/**
 * The coarse presentation of a repository's ingest status.
 * @module repoStatus
 */
import type Repository from "@/types/repository";

/** How a repository's status is presented. */
export type StatusView = {
  kind: "ready" | "ingesting" | "failed";
  label: string;
  color: string;
};

/**
 * Maps a repository status to its badge.
 *
 * Every status that is neither `ready` nor `failed` is an ingest still in
 * progress.
 *
 * @param status The repository's `status`.
 * @returns The badge's kind, label and colour.
 */
export function statusView(status: string): StatusView {
  if (status === "ready") return { kind: "ready", label: "Ready", color: "#22c55e" };
  if (status === "failed") return { kind: "failed", label: "Failed", color: "#ef4444" };
  return { kind: "ingesting", label: "Ingesting", color: "#f6339a" };
}

/**
 * Describes the background-update state shown on cards and the overview.
 *
 * @param repo The repository.
 * @returns The label and its dot colour, and whether the dot should blink.
 */
export function syncView(repo: Repository): { label: string; color: string; live: boolean } {
  if (!repo.auto_update_enabled) {
    return { label: "Auto-update off", color: "#3f3f46", live: false };
  }
  switch (repo.sync_status) {
    case "queued":
    case "checking":
    case "updating":
      return { label: "Updating", color: "#53eafd", live: true };
    case "failed":
      return { label: "Update failed", color: "#ef4444", live: false };
    default:
      return {
        label: `Auto-update · ${repo.auto_update_interval_hours}h`,
        color: "#00b8db",
        live: false,
      };
  }
}
