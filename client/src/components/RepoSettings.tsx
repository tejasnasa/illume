/**
 * Repository settings: auto-update, the analysed version, export and
 * rebuild, and deletion.
 * @module RepoSettings
 */
"use client";

import deleteRepoAction from "@/actions/deleteRepo";
import regenerateRepoAction from "@/actions/regenerateRepo";
import AutoUpdateSection from "@/components/AutoUpdateSection";
import Repository from "@/types/repository";
import { splitRepoName } from "@/utils/repoName";
import { runRedirectingAction } from "@/utils/redirectingAction";
import { useRouter } from "next/navigation";
import { useState } from "react";
import ExportIllumeButton from "./ExportIllumeButton";
import GitGraph from "./GitGraph";
import Button from "./ui/Button";
import Input from "./ui/Input";
import ConfirmBody from "./ui/ConfirmBody";
import Modal from "./ui/Modal";
import SettingsSection, { SettingsRow } from "./ui/SettingsSection";

/**
 * Renders the settings sections for one repository.
 *
 * @param repo - The repository whose settings are being shown. The auto-update
 *               section reads its full record so it can render status and counts.
 * @returns The settings sections, with confirmation dialogs for destructive actions.
 */
export default function RepoSettings({ repo }: { repo: Repository }) {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // Deleting is permanent, so the button stays disabled until the name is typed.
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [regenerateError, setRegenerateError] = useState<string | null>(null);

  // Owner/name feed the version graph; an unparseable URL hides that section.
  const parsed = splitRepoName(repo.github_url, "");
  const owner = parsed.owner;
  const repoName = parsed.name;

  /**
   * Re-ingests the repo at the chosen branch/commit, then returns to dashboard.
   *
   * @param branch - Branch to re-ingest.
   * @param commitSha - Optional pinned commit; null re-ingests the branch tip.
   */
  const handleReingest = async (branch: string, commitSha: string | null) => {
    setIsSubmitting(true);
    setError(null);
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repo.id}/reingest`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({
            branch,
            commit_sha: commitSha,
          }),
        },
      );

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.message || errorData.detail || "Failed to trigger re-ingestion");
      }

      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Failed to start re-ingestion process");
    } finally {
      setIsSubmitting(false);
    }
  };

  /**
   * Rebuilds the repository's analysis, holding the confirm button in its
   * loading state until the action settles. Like delete, the redirect that
   * ends a successful run unmounts this tree, so the spinner is only cleared
   * when there is a failure to report.
   */
  const handleRegenerate = async () => {
    setIsRegenerating(true);
    setRegenerateError(null);
    const failure = await runRedirectingAction(
      () => regenerateRepoAction(repo.id),
      "Failed to regenerate repository",
    );
    if (failure) {
      setRegenerateError(failure);
      setIsRegenerating(false);
    }
  };

  /**
   * Deletes the repository, holding the confirm button in its loading state
   * until the action settles. Cleared only on failure, for the same reason as
   * regenerate.
   */
  const handleDelete = async () => {
    setIsDeleting(true);
    setDeleteError(null);
    const failure = await runRedirectingAction(
      () => deleteRepoAction(repo.id),
      "Failed to delete repository",
    );
    if (failure) {
      setDeleteError(failure);
      setIsDeleting(false);
    }
  };

  const shortSha = repo.ingested_commit_sha?.slice(0, 7);

  return (
    <div className="flex flex-col">
      <SettingsSection
        id="settings-auto"
        title="Auto-update"
        description="Keep this repository in step with its branch. Only changed files are re-read, and the app stays usable while it updates."
      >
        <AutoUpdateSection repo={repo} />
      </SettingsSection>

      {owner && repoName && (
        <SettingsSection
          id="settings-version"
          title="Version"
          description={
            <>
              Currently analysing{" "}
              <span className="font-pixel text-(--foreground)">
                {repo.ingested_branch ?? "a detached commit"}
              </span>
              {shortSha && (
                <>
                  {" "}
                  at <span className="font-pixel text-(--accent)">{shortSha}</span>
                </>
              )}
              . Pick another branch or commit to re-ingest. Re-ingesting
              rebuilds everything for that version and clears this
              repository&apos;s chats.
            </>
          }
        >
          <div className="flex flex-col gap-2 rounded-md border border-(--border) bg-(--card) pt-5">
            {error && (
              <div
                role="alert"
                className="mx-5 rounded-sm border border-red-500/25 bg-red-500/5 p-3 text-xs text-red-300"
              >
                {error}
              </div>
            )}
            <GitGraph
              owner={owner}
              repo={repoName}
              onSelect={handleReingest}
              isSubmitting={isSubmitting}
              note="Rebuilds everything for that version"
            />
          </div>
        </SettingsSection>
      )}

      <SettingsSection
        id="settings-export"
        title="Export and rebuild"
        description="Take the analysis with you, or regenerate it from the current snapshot."
      >
        <SettingsRow
          title="Export for AI agents"
          description="A compressed .illume context file with the brief, reading order, glossary and hotspots, ready for an agent to read."
          action={<ExportIllumeButton repo_id={repo.id} />}
        />
        <SettingsRow
          title="Regenerate analysis"
          description="Re-analyses the repository and rebuilds every insight from scratch."
          action={
            <Modal
              className="w-[min(30rem,calc(100vw-2rem))]"
              dialogLabel="Regenerate analysis"
              trigger={
                <Button size="sm" variant="ghost" className="shrink-0">
                  <span aria-hidden="true">↻</span> Regenerate
                </Button>
              }
            >
              <ConfirmBody
                title="Regenerate analysis?"
                footer={
                  <>
                    <span role="alert" className="max-w-[60%] text-xs text-red-300">
                      {regenerateError}
                    </span>
                    <Button onClick={handleRegenerate} loading={isRegenerating} size="sm">
                      Regenerate
                    </Button>
                  </>
                }
              >
                <p className="m-0">
                  The repository is rebuilt under the same address. It is
                  unavailable while the new analysis runs, and you are taken
                  back to the dashboard.
                </p>
              </ConfirmBody>
            </Modal>
          }
        />
      </SettingsSection>

      <SettingsSection
        id="settings-danger"
        title="Danger zone"
        tone="danger"
        description="This cannot be undone."
      >
        <SettingsRow
          tone="danger"
          title="Delete this repository"
          description="Removes the graph, guide, glossary, chats and search index. Your GitHub repository is not touched."
          action={
            <Modal
              className="w-[min(30rem,calc(100vw-2rem))]"
              dialogLabel="Delete repository"
              trigger={
                <Button size="sm" variant="danger" className="shrink-0">
                  Delete repository
                </Button>
              }
            >
              <ConfirmBody
                title="Delete repository"
                danger
                footer={
                  <>
                    <span role="alert" className="max-w-[60%] text-xs text-red-300">
                      {deleteError}
                    </span>
                    <Button
                      onClick={handleDelete}
                      loading={isDeleting}
                      disabled={deleteConfirmation !== repo.name}
                      size="sm"
                      className="border-none bg-red-500 text-white hover:bg-red-600 disabled:bg-red-500/40"
                    >
                      Delete
                    </Button>
                  </>
                }
              >
                <p className="m-0">
                  This permanently deletes the repository and all of its
                  analysis, chat history and settings. Type{" "}
                  <span className="font-pixel text-(--foreground)">{repo.name}</span> to
                  confirm.
                </p>
                <Input
                  value={deleteConfirmation}
                  onChange={(e) => setDeleteConfirmation(e.target.value)}
                  aria-label="Repository name to confirm deletion"
                  placeholder={repo.name}
                  autoComplete="off"
                  className="w-full"
                />
              </ConfirmBody>
            </Modal>
          }
        />
      </SettingsSection>
    </div>
  );
}
