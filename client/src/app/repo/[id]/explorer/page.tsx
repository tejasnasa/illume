/**
 * File explorer route showing the repository tree with guardrails.
 * @module ExplorerPage
 */
import { getRepoGraph } from "@/api/graph";
import { GetGuide } from "@/api/guide";
import { GetRepository } from "@/api/repository";
import ExplorerClient from "@/components/ExplorerClient";

/**
 * Server-rendered explorer: loads the file-level graph and reading guide.
 *
 * The guide is optional: without it the tree still works, just without a
 * reading order or notes.
 *
 * @param params - Route params promise resolving to the repository number.
 * @param searchParams - Query promise; `file` names the file to open.
 * @returns Explorer client view, or an error card when the graph is missing.
 */
export default async function ExplorerPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ file?: string | string[] }>;
}) {
  const { id } = await params;
  const { file } = await searchParams;
  // Route param arrives as a string; numeric id is required by the API layer.
  const repo = await GetRepository(Number(id));

  const [graphData, guide] = await Promise.all([
    getRepoGraph(repo.id, "file").catch(() => null),
    GetGuide(repo.id).catch(() => null),
  ]);

  return (
    <div className="mx-auto w-full max-w-7xl px-4 pt-8 pb-16 sm:px-6">
      {!graphData ? (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-md border border-red-500/25 bg-red-500/5 p-5 text-sm text-red-300"
        >
          <span aria-hidden="true" className="font-pixel text-red-400">
            !
          </span>
          <p className="m-0">Failed to load file explorer data.</p>
        </div>
      ) : (
        <ExplorerClient
          graphData={graphData}
          github_url={repo.github_url}
          repoId={repo.id}
          repoNumber={repo.repo_number}
          guide={guide}
          commitSha={repo.ingested_commit_sha}
          branch={repo.ingested_branch}
          initialPath={typeof file === "string" ? file : null}
        />
      )}
    </div>
  );
}
