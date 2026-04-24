import { getRepoGraph } from "@/api/graph";
import { GetRepository } from "@/api/repository";
import ExplorerClient from "@/components/ExplorerClient";
import {
  FolderOpenIcon,
  WarningDiamondIcon,
} from "@phosphor-icons/react/dist/ssr";

export default async function ExplorerPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const repo = await GetRepository(Number(id));

  const graphData = await getRepoGraph(repo.id, "file");

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
        <ExplorerClient graphData={graphData} github_url={repo.github_url} repoId={repo.id} />
      )}
    </div>
  );
}
