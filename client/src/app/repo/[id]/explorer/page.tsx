/**
 * File explorer route showing the repository tree with guardrails.
 * @module ExplorerPage
 */
import { getRepoGraph } from "@/api/graph";
import { GetGuide } from "@/api/guide";
import { GetRepository } from "@/api/repository";
import ExplorerClient from "@/components/ExplorerClient";
import {
  FolderOpenIcon,
  WarningDiamondIcon,
} from "@phosphor-icons/react/dist/ssr";

/**
 * Server-rendered explorer: loads file-level graph and reading guide.
 *
 * @param params - Route params promise resolving to the repository id.
 * @returns Explorer client view, or an error card when the graph is missing.
 */
export default async function ExplorerPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  // Route param arrives as a string; numeric id is required by the API layer.
  const repo = await GetRepository(Number(id));

  const graphData = await getRepoGraph(repo.id, "file");
  const guide = await GetGuide(repo.id);

  return (
    <div className="mx-auto max-w-7xl py-12">

      {!graphData ? (
        <div className="glass-card rounded-sm overflow-hidden border border-(--border) bg-(--card)/40 p-2">
          <div className="p-6 rounded-sm border border-(--destructive)/30 bg-(--destructive)/10 text-(--destructive) flex items-start gap-4">
            <WarningDiamondIcon
              size={24}
              weight="duotone"
              className="shrink-0 mt-0.5"
            />
            <p>Failed to load file explorer data.</p>
          </div>
        </div>
      ) : (
        <ExplorerClient graphData={graphData} github_url={repo.github_url} repoId={repo.id} guide={guide} />
      )}
    </div>
  );
}
