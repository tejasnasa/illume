/**
 * Repository ingestion status vocabulary.
 *
 * @module RepoStatus
 *
 * The backend stores a repository's pipeline state in one column, and the
 * enum it accepts is fixed by the database type ``repo_status``:
 * ``pending | cloning | parsing | embedding | analyzing | ready | failed``.
 * The first four are the moving states, the last two are terminal.
 *
 * Everything in this module is a pure function over that vocabulary, so the
 * rules about what a status *means* -- when the screen should poll, which
 * copy to show, which colour to use -- live in one place instead of being
 * re-derived at every call site.
 *
 * The status copy is ported from the web app's live ingest view
 * (``client/src/components/IngestFlow.tsx`` and the stage labels in
 * ``client/src/utils/ingestFlow.ts``) so both clients describe the same
 * pipeline with the same words.
 */

/** Every status the backend's ``repo_status`` enum accepts. */
export const REPO_STATUS = {
  /** Created, but no worker has claimed the job yet. */
  PENDING: "pending",
  /** The repository is being fetched from GitHub. */
  CLONING: "cloning",
  /** The tree is being walked and every file parsed. */
  PARSING: "parsing",
  /** Embeddings and the architecture brief are being generated. */
  EMBEDDING: "embedding",
  /** Reserved by the enum; the pipeline never writes it. */
  ANALYZING: "analyzing",
  /** Analysis finished; the repository is fully indexed. */
  READY: "ready",
  /** The pipeline gave up. */
  FAILED: "failed",
} as const;

/** One of the statuses in :data:`REPO_STATUS`. */
export type RepoStatus = (typeof REPO_STATUS)[keyof typeof REPO_STATUS];

/**
 * Statuses the pipeline will not leave on its own.
 *
 * A repository sitting in one of these needs no polling: either the data is
 * there, or it never will be without another ingest.
 */
export const TERMINAL_STATUSES: ReadonlySet<string> = new Set<string>([
  REPO_STATUS.READY,
  REPO_STATUS.FAILED,
]);

/**
 * ``sync_status`` values that mean a background sync is in flight.
 *
 * A sync deliberately keeps ``status='ready'`` -- the graph, the navigation
 * and the repository page all key off that -- so the *only* signal that a
 * sync is running is this field.
 */
export const ACTIVE_SYNC_STATUSES: ReadonlySet<string> = new Set<string>([
  "queued",
  "checking",
  "updating",
]);

/**
 * How long a failure is still assumed to be retrying.
 *
 * The ingest task retries up to three times with a ten-second countdown, so
 * a freshly-failed repository is usually mid-retry rather than dead. The web
 * app makes the same distinction with the same number: it shows "Failed,
 * retrying…" until the retry grace period expires, and "Ingestion failed"
 * after it.
 */
export const RETRY_GRACE_MS = 15_000;

/**
 * The pipeline stage each status corresponds to.
 *
 * The web client names the *first* stage of the phase, which is what a user
 * watching a coarse status would recognise: ``parsing`` is "Parse files" even
 * though the parse phase also resolves dependencies and mines git history.
 */
const STATUS_STAGE_LABELS: Record<string, string> = {
  [REPO_STATUS.PENDING]: "Queued — waiting for a worker",
  [REPO_STATUS.CLONING]: "Fetch Repo",
  [REPO_STATUS.PARSING]: "Parse files",
  [REPO_STATUS.EMBEDDING]: "Generate Embeddings",
  [REPO_STATUS.ANALYZING]: "Analyze Architecture",
  [REPO_STATUS.READY]: "Ready",
};

/**
 * A one-line explanation of what the pipeline is doing, shown under the
 * headline. The web client draws a diagram instead; on a phone the diagram
 * arrives with the live stream, so this screen settles for the sentence.
 */
const STATUS_DESCRIPTIONS: Record<string, string> = {
  [REPO_STATUS.PENDING]: "Waiting for a worker to pick up the ingest.",
  [REPO_STATUS.CLONING]: "Fetching the repository from GitHub.",
  [REPO_STATUS.PARSING]:
    "Walking the tree, parsing every file and mapping the connections between them.",
  [REPO_STATUS.EMBEDDING]:
    "Generating embeddings and writing the architecture brief.",
  [REPO_STATUS.ANALYZING]: "Writing the architecture brief.",
  [REPO_STATUS.READY]: "The repository is indexed and ready to explore.",
  [REPO_STATUS.FAILED]:
    "The ingest stopped before it finished. The pipeline retries a few times before giving up.",
};

/**
 * The ingestion pipeline, in the order it runs.
 *
 * The labels are the web client's stage names (``client/src/utils/
 * ingestFlow.ts``), so a reader who has seen the web app recognises them.
 * The order is the pipeline's spine: the pull-request fetch is listed last
 * because its result is joined at the very end, even though it runs
 * alongside the parse stage.
 */
export const PIPELINE_STAGES: readonly { id: string; label: string }[] = [
  { id: "clone", label: "Fetch Repo" },
  { id: "parse", label: "Parse files" },
  { id: "resolve_dependencies", label: "Map Connections" },
  { id: "compute_fan_metrics", label: "Rank Impact" },
  { id: "detect_stack", label: "Identify Stack" },
  { id: "git_history", label: "Mine Git History" },
  { id: "criticality", label: "Score Risk" },
  { id: "glossary", label: "Create Glossary" },
  { id: "reading_order", label: "Create Reading Order" },
  { id: "generate_embeddings", label: "Generate Embeddings" },
  { id: "brief", label: "Analyze Architecture" },
  { id: "pr_fetch", label: "Gather PRs" },
  { id: "ready", label: "Ready" },
];

/** The three states a pipeline stage can be drawn in. */
export type StageState = "done" | "active" | "pending";

/**
 * The stages a status of ``embedding`` proves have already finished.
 *
 * The chain is sequential, so the embedding status -- written once the
 * glossary and reading-order join returned -- proves every stage before it.
 */
const DONE_ONCE_EMBEDDING = [
  "clone",
  "parse",
  "resolve_dependencies",
  "compute_fan_metrics",
  "detect_stack",
  "git_history",
  "criticality",
  "glossary",
  "reading_order",
] as const;

/**
 * Work out which pipeline stages a coarse status implies.
 *
 * The web client seeds its diagram the same way, and for the same reason:
 * the live stream only delivers frames published after it connects, so a
 * page opened two minutes into an ingest has to reconstruct what already
 * happened from the status alone.
 *
 * The mapping is deliberately pessimistic -- ``parsing`` spans the parse
 * stage through the reading order, so it can only prove that the clone
 * finished. Showing a stage as pending when it has actually completed is
 * the safe direction to be wrong in.
 *
 * @param status - The repository's ``status`` field.
 * @returns The state of every stage in :data:`PIPELINE_STAGES`.
 */
export function stageStatesFromStatus(
  status: string | null | undefined,
): Record<string, StageState> {
  const states: Record<string, StageState> = {};
  for (const stage of PIPELINE_STAGES) states[stage.id] = "pending";

  const mark = (ids: readonly string[], state: StageState) => {
    for (const id of ids) if (id in states) states[id] = state;
  };

  switch (status) {
    case REPO_STATUS.CLONING:
      mark(["clone"], "active");
      break;

    case REPO_STATUS.PARSING:
      // Only the clone is provable here; everything from parse onwards is
      // still ambiguous, so the earliest candidate takes `active`.
      mark(["clone"], "done");
      mark(["parse", "pr_fetch"], "active");
      break;

    case REPO_STATUS.EMBEDDING:
      mark(DONE_ONCE_EMBEDDING, "done");
      mark(["generate_embeddings", "brief", "pr_fetch"], "active");
      break;

    case REPO_STATUS.ANALYZING:
      mark(DONE_ONCE_EMBEDDING, "done");
      mark(["brief"], "active");
      break;

    case REPO_STATUS.READY:
      mark(
        PIPELINE_STAGES.map((stage) => stage.id),
        "done",
      );
      break;

    default:
      // Nothing is provable. `failed` additionally renders a failure
      // affordance at the view level, because the coarse status does not
      // say which stage gave up.
      break;
  }

  return states;
}

/**
 * Whether the repository has been fully indexed.
 *
 * @param status - The repository's ``status`` field.
 * @returns ``true`` when the status is ``ready``.
 */
export function isReadyStatus(status: string | null | undefined): boolean {
  return status === REPO_STATUS.READY;
}

/**
 * Whether the pipeline gave up on the repository.
 *
 * @param status - The repository's ``status`` field.
 * @returns ``true`` when the status is ``failed``.
 */
export function isFailedStatus(status: string | null | undefined): boolean {
  return status === REPO_STATUS.FAILED;
}

/**
 * Whether the repository is still being worked on.
 *
 * @param status - The repository's ``status`` field.
 * @returns ``true`` for every status that is neither terminal.
 */
export function isPendingStatus(status: string | null | undefined): boolean {
  if (!status) return false;
  return !TERMINAL_STATUSES.has(status);
}

/**
 * Whether a background sync is currently running.
 *
 * @param syncStatus - The repository's ``sync_status`` field.
 * @returns ``true`` for ``queued``, ``checking`` and ``updating``.
 */
export function isSyncActive(syncStatus: string | null | undefined): boolean {
  if (!syncStatus) return false;
  return ACTIVE_SYNC_STATUSES.has(syncStatus);
}

/**
 * Whether the screen should keep refetching the repository.
 *
 * Two independent reasons to poll, matching the web client: the initial
 * ingest has not settled, or a background sync is running. The sync case
 * matters because a sync keeps ``status='ready'`` -- without it, the
 * repository page would never notice that anything changed.
 *
 * @param status - The repository's ``status`` field.
 * @param syncStatus - The repository's ``sync_status`` field.
 * @returns ``true`` while a refetch could still change the screen.
 */
export function shouldPoll(
  status: string | null | undefined,
  syncStatus: string | null | undefined,
): boolean {
  return isPendingStatus(status) || isSyncActive(syncStatus);
}

/**
 * The headline shown above a repository that is not ready.
 *
 * @param status - The repository's ``status`` field.
 * @param failureAgeMs - How long the repository has been in the failed state,
 *   in milliseconds. Inside the retry grace period the pipeline is probably
 *   still retrying, so the copy says so.
 * @returns The headline text.
 */
export function statusHeadline(
  status: string | null | undefined,
  failureAgeMs?: number,
): string {
  if (status === REPO_STATUS.FAILED) {
    return failureAgeMs !== undefined && failureAgeMs < RETRY_GRACE_MS
      ? "Failed, retrying…"
      : "Ingestion failed";
  }
  return STATUS_STAGE_LABELS[status ?? ""] ?? "Starting…";
}

/**
 * The supporting sentence shown under the headline.
 *
 * @param status - The repository's ``status`` field.
 * @returns The description text.
 */
export function statusDescription(status: string | null | undefined): string {
  return STATUS_DESCRIPTIONS[status ?? ""] ?? "Working on it.";
}

/**
 * The visual tone a status should be rendered in.
 *
 * @param status - The repository's ``status`` field.
 * @returns ``success`` for ready, ``destructive`` for failed, ``pending``
 *   for everything still in flight.
 */
export function statusTone(
  status: string | null | undefined,
): "success" | "destructive" | "pending" {
  if (isReadyStatus(status)) return "success";
  if (isFailedStatus(status)) return "destructive";
  return "pending";
}
