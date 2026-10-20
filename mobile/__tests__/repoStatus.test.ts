/**
 * Tests for the repository status vocabulary.
 *
 * The status rules are the contract between the backend's ``repo_status``
 * enum and every screen that renders a repository, so they are tested as
 * pure functions rather than through a rendered screen.
 */

import {
  ACTIVE_SYNC_STATUSES,
  PIPELINE_STAGES,
  REPO_STATUS,
  RETRY_GRACE_MS,
  isFailedStatus,
  isPendingStatus,
  isReadyStatus,
  isSyncActive,
  shouldPoll,
  stageStatesFromStatus,
  statusDescription,
  statusHeadline,
  statusTone,
} from "@/lib/repoStatus";

describe("repo status", () => {
  it("treats ready and failed as the only terminal statuses", () => {
    expect(isReadyStatus("ready")).toBe(true);
    expect(isFailedStatus("failed")).toBe(true);

    expect(isPendingStatus("ready")).toBe(false);
    expect(isPendingStatus("failed")).toBe(false);

    for (const status of ["pending", "cloning", "parsing", "embedding"]) {
      expect(isPendingStatus(status)).toBe(true);
    }
  });

  it("knows which sync statuses mean a sync is in flight", () => {
    for (const status of ACTIVE_SYNC_STATUSES) {
      expect(isSyncActive(status)).toBe(true);
    }

    expect(isSyncActive("idle")).toBe(false);
    expect(isSyncActive("failed")).toBe(false);
    expect(isSyncActive(null)).toBe(false);
    expect(isSyncActive(undefined)).toBe(false);
  });

  it("polls while an ingest is unsettled or a sync is running", () => {
    expect(shouldPoll("parsing", "idle")).toBe(true);
    expect(shouldPoll("pending", "idle")).toBe(true);
    expect(shouldPoll("failed", "idle")).toBe(false);
    expect(shouldPoll("ready", "idle")).toBe(false);

    // A sync keeps `status='ready'` on purpose, so `sync_status` is the
    // only signal that something is still moving.
    expect(shouldPoll("ready", "updating")).toBe(true);
    expect(shouldPoll("ready", "queued")).toBe(true);
    expect(shouldPoll("ready", "checking")).toBe(true);
  });

  it("uses the web client's headline for every status", () => {
    expect(statusHeadline("pending")).toBe("Queued — waiting for a worker");
    expect(statusHeadline("cloning")).toBe("Fetch Repo");
    expect(statusHeadline("parsing")).toBe("Parse files");
    expect(statusHeadline("embedding")).toBe("Generate Embeddings");
    expect(statusHeadline("ready")).toBe("Ready");
  });

  it("distinguishes a failure that is still retrying from a dead one", () => {
    expect(statusHeadline("failed", 0)).toBe("Failed, retrying…");
    expect(statusHeadline("failed", RETRY_GRACE_MS - 1)).toBe(
      "Failed, retrying…",
    );
    expect(statusHeadline("failed", RETRY_GRACE_MS)).toBe("Ingestion failed");
    expect(statusHeadline("failed", RETRY_GRACE_MS + 60_000)).toBe(
      "Ingestion failed",
    );
  });

  it("falls back to a generic headline for an unknown status", () => {
    expect(statusHeadline("something-new")).toBe("Starting…");
    expect(statusHeadline(undefined)).toBe("Starting…");
    expect(statusDescription("something-new")).toBe("Working on it.");
  });

  it("colours a status by tone", () => {
    expect(statusTone("ready")).toBe("success");
    expect(statusTone("failed")).toBe("destructive");
    expect(statusTone("parsing")).toBe("pending");
    expect(statusTone(undefined)).toBe("pending");
  });

  it("seeds the pipeline from a coarse status, pessimistically", () => {
    const cloning = stageStatesFromStatus("cloning");
    expect(cloning.clone).toBe("active");
    expect(cloning.parse).toBe("pending");

    const parsing = stageStatesFromStatus("parsing");
    // Only the clone is provable from a `parsing` status.
    expect(parsing.clone).toBe("done");
    expect(parsing.parse).toBe("active");
    expect(parsing.glossary).toBe("pending");

    const embedding = stageStatesFromStatus("embedding");
    expect(embedding.glossary).toBe("done");
    expect(embedding.reading_order).toBe("done");
    expect(embedding.generate_embeddings).toBe("active");

    const ready = stageStatesFromStatus("ready");
    for (const stage of PIPELINE_STAGES) {
      expect(ready[stage.id]).toBe("done");
    }
  });

  it("proves nothing from a failed or pending status", () => {
    for (const status of ["failed", "pending", "unknown"]) {
      const states = stageStatesFromStatus(status);
      for (const stage of PIPELINE_STAGES) {
        expect(states[stage.id]).toBe("pending");
      }
    }
  });

  it("keeps the pipeline stage list in the order the pipeline runs", () => {
    const ids = PIPELINE_STAGES.map((stage) => stage.id);
    expect(ids[0]).toBe("clone");
    expect(ids[ids.length - 1]).toBe("ready");
    expect(ids).toContain("pr_fetch");
  });

  it("exposes the backend's status enum", () => {
    expect(Object.values(REPO_STATUS)).toEqual(
      expect.arrayContaining([
        "pending",
        "cloning",
        "parsing",
        "embedding",
        "ready",
        "failed",
      ]),
    );
  });
});
