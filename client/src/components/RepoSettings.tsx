/**
 * Repository management panel with export and danger-zone actions.
 * @module RepoSettings
 */
import deleteRepoAction from "@/actions/deleteRepo";
import regenerateRepoAction from "@/actions/regenerateRepo";
import AutoUpdateSection from "@/components/AutoUpdateSection";
import Repository from "@/types/repository";
import {
  GearFineIcon,
  GitBranchIcon,
  RepeatIcon,
  TrashIcon,
} from "@phosphor-icons/react/dist/ssr";
import { useRouter } from "next/navigation";
import { useState } from "react";
import ExportIllumeButton from "./ExportIllumeButton";
import GitGraph from "./GitGraph";
import Button from "./ui/Button";
import Modal from "./ui/Modal";

/**
 * Renders export, delete, regenerate, auto-update, and version re-ingest controls.
 *
 * @param repo - The repository whose settings are being shown. The auto-update
 *               section reads its full record so it can render status and counts.
 * @returns Settings panel with confirmation modals for destructive actions.
 */
export default function RepoSettings({ repo }: { repo: Repository }) {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Owner/name feed the version graph; empty strings hide that section.
  const match = repo.github_url.match(
    /^https:\/\/github\.com\/([\w.-]+)\/([\w.-]+)\/?$/,
  );
  const owner = match ? match[1] : "";
  const repoName = match ? match[2].replace(/\.git$/, "") : "";

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
        const errorData = await res.json();
        throw new Error(errorData.message || "Failed to trigger re-ingestion");
      }

      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Failed to start re-ingestion process");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="p-4 max-h-[90vh] overflow-y-auto custom-scrollbar min-w-2xl">
      <div className="flex items-center gap-3 mb-6 text-(--primary)">
        <GearFineIcon size={28} weight="duotone" />
        <h1 className="text-3xl font-bold text-(--foreground) tracking-tight">
          Settings
        </h1>
      </div>

      <AutoUpdateSection repo={repo} />

      <div className="mt-8 rounded-sm border border-(--primary)/20 divide-y divide-(--primary)/10">
        <div className="px-5 py-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-(--primary)">
            Export Repository
          </p>
        </div>

        <div className="flex items-center justify-between px-5 py-4">
          <div>
            <p className="text-sm font-medium text-(--foreground)">
              Download .illume file
            </p>
            <p className="text-xs text-(--muted-foreground) mt-0.5 max-w-[280px]">
              Get a compressed codebase context file optimized for AI models to
              read instantly.
            </p>
          </div>
          <ExportIllumeButton repo_id={repo.id} />
        </div>
      </div>

      <div className="mt-8 rounded-sm border border-red-500/20 divide-y divide-red-500/10">
        <div className="px-5 py-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-red-400">
            Danger Zone
          </p>
        </div>

        <div className="flex items-center justify-between px-5 py-4">
          <div>
            <p className="text-sm font-medium text-(--foreground)">
              Regenerate Repository
            </p>
            <p className="text-xs text-(--muted-foreground) mt-0.5">
              Re-analyze and rebuild all repository insights.
            </p>
          </div>
          <Modal
            className="p-4 w-120"
            trigger={
              <Button size="sm" className="gap-1.5 shrink-0">
                <RepeatIcon weight="duotone" size={15} />
                Regenerate
              </Button>
            }
          >
            <div className="flex items-center gap-3 mb-1 text-(--primary) text-2xl">
              <RepeatIcon weight="duotone" />
              <h1 className="font-bold text-(--foreground) tracking-tight">
                Regenerate Repository
              </h1>
            </div>
            <p className="text-(--muted-foreground) mb-12 text-sm">
              Are you sure you want to regenerate this repository?
            </p>
            <Button
              onClick={() => regenerateRepoAction(repo.id)}
              size="sm"
              className="font-semibold absolute bottom-4 right-4"
            >
              REGENERATE
            </Button>
          </Modal>
        </div>

        {owner && repoName && (
          <div className="flex items-center justify-between px-5 py-4">
            <div>
              <p className="text-sm font-medium text-(--foreground)">
                Ingest Different Version
              </p>
              <p className="text-xs text-(--muted-foreground) mt-0.5">
                Re-ingest the repository from a specific branch or commit.
              </p>
            </div>
            <Modal
              className="w-full min-w-2xl p-6"
              trigger={
                <Button size="sm" className="gap-1.5 shrink-0">
                  <GitBranchIcon weight="duotone" size={15} />
                  Change Version
                </Button>
              }
            >
              <div className="flex flex-col gap-4 max-w-2xl">
                <div>
                  <h1 className="text-2xl font-bold text-(--foreground) tracking-tight flex items-center gap-2">
                    <GitBranchIcon className="text-(--primary)" />
                    Re-ingest Specific Version
                  </h1>
                  <p className="text-xs text-(--muted-foreground) mt-1">
                    Select a branch or commit from the repository history to
                    re-analyze.
                  </p>
                </div>

                {error && (
                  <div className="p-3 rounded bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
                    {error}
                  </div>
                )}

                <GitGraph
                  owner={owner}
                  repo={repoName}
                  onSelect={handleReingest}
                  isSubmitting={isSubmitting}
                />
              </div>
            </Modal>
          </div>
        )}

        <div className="flex items-center justify-between px-5 py-4">
          <div>
            <p className="text-sm font-medium text-(--foreground)">
              Delete Repository
            </p>
            <p className="text-xs text-(--muted-foreground) mt-0.5">
              Permanently remove this repository and all its data.
            </p>
          </div>
          <Modal
            className="p-4 w-120"
            trigger={
              <Button
                size="sm"
                className="border-red-500 bg-white text-red-500 hover:border-red-700 border-2 gap-1.5 shrink-0"
              >
                <TrashIcon weight="duotone" size={15} />
                Delete
              </Button>
            }
          >
            <div className="flex items-center gap-3 mb-1 text-red-400 text-2xl">
              <TrashIcon weight="duotone" />
              <h1 className="font-bold text-(--foreground) tracking-tight">
                Delete Repository
              </h1>
            </div>
            <p className="text-(--muted-foreground) mb-12 text-sm">
              Are you sure you want to delete this repository?
            </p>
            <Button
              onClick={() => deleteRepoAction(repo.id)}
              size="sm"
              className="font-semibold absolute bottom-4 right-4 bg-red-500 hover:bg-red-600 text-white border-none"
            >
              DELETE
            </Button>
          </Modal>
        </div>
      </div>
    </div>
  );
}
