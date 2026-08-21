import deleteRepoAction from "@/actions/deleteRepo";
import regenerateRepoAction from "@/actions/regenerateRepo";
import {
  GearFineIcon,
  RepeatIcon,
  TrashIcon,
  GitBranchIcon,
} from "@phosphor-icons/react/dist/ssr";
import ExportIllumeButton from "./ExportIllumeButton";
import Button from "./ui/Button";
import Modal from "./ui/Modal";
import GitGraph from "./GitGraph";
import { useState } from "react";
import { useRouter } from "next/navigation";

export default function RepoSettings({
  repo_id,
  github_url,
}: {
  repo_id: string;
  github_url: string;
}) {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const match = github_url.match(/^https:\/\/github\.com\/([\w.-]+)\/([\w.-]+)\/?$/);
  const owner = match ? match[1] : "";
  const repoName = match ? match[2].replace(/\.git$/, "") : "";

  const handleReingest = async (branch: string, commitSha: string | null) => {
    setIsSubmitting(true);
    setError(null);
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repo_id}/reingest`,
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
    <div className="p-4 max-h-[90vh] overflow-y-auto custom-scrollbar">
      <div className="flex items-center gap-3 mb-6 text-(--primary)">
        <GearFineIcon size={28} weight="duotone" />
        <h1 className="text-3xl font-bold text-(--foreground) tracking-tight">
          Settings
        </h1>
      </div>

      <div className="mt-8 rounded-sm border border-(--primary)/20 divide-y divide-(--primary)/10 w-125">
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
          <ExportIllumeButton repo_id={repo_id} />
        </div>
      </div>

      <div className="mt-8 rounded-sm border border-red-500/20 divide-y divide-red-500/10 w-125">
        <div className="px-5 py-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-red-400">
            Danger Zone
          </p>
        </div>

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
                className="border-red-500/40 bg-white text-red-500 hover:border-red-500/60 gap-1.5 shrink-0"
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
              onClick={() => deleteRepoAction(repo_id)}
              size="sm"
              className="font-semibold absolute bottom-4 right-4 bg-red-500 hover:bg-red-600 text-white border-none"
            >
              DELETE
            </Button>
          </Modal>
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
              onClick={() => regenerateRepoAction(repo_id)}
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
              className="w-full max-w-2xl p-6"
              trigger={
                <Button size="sm" className="gap-1.5 shrink-0">
                  <GitBranchIcon weight="duotone" size={15} />
                  Change Version
                </Button>
              }
            >
              <div className="flex flex-col gap-4">
                <div>
                  <h1 className="text-2xl font-bold text-(--foreground) tracking-tight flex items-center gap-2">
                    <GitBranchIcon className="text-(--primary)" />
                    Re-ingest Specific Version
                  </h1>
                  <p className="text-xs text-(--muted-foreground) mt-1">
                    Select a branch or commit from the repository history to re-analyze.
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
      </div>
    </div>
  );
}
