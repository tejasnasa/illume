/**
 * Dependency graph route with file/symbol granularity.
 * @module GraphPage
 */
import { getRepoGraph } from "@/api/graph";
import { GetGuide } from "@/api/guide";
import { GetRepository } from "@/api/repository";
import GraphClient from "@/components/GraphClient";

/**
 * Server-rendered graph page: loads graph data and guide for the client view.
 *
 * @param params - Route params promise resolving to the repository id.
 * @param searchParams - Query params promise carrying the graph level.
 * @returns Graph client visualization.
 */
export default async function GraphPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { id } = await params;
  const repo = await GetRepository(Number(id));
  const { level } = await searchParams;

  // Default to file-level when no level query is present.
  const currentLevel = (level as string) || "file";

  const graphData = await getRepoGraph(
    repo.id,
    currentLevel as "file" | "symbol",
  );
  const guide = await GetGuide(repo.id);

  return (
    <GraphClient
      graphData={graphData}
      currentLevel={currentLevel}
      repoId={id}
      github_url={repo.github_url}
      guide={guide}
    />
  );
}
