import { getRepoGraph } from "@/api/graph";
import { GetRepository } from "@/api/repository";
import GraphClient from "@/components/GraphClient";

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

  const currentLevel = (level as string) || "file";

  const graphData = await getRepoGraph(
    repo.id,
    currentLevel as "file" | "symbol",
  );

  return (
    <GraphClient
      graphData={graphData}
      currentLevel={currentLevel}
      repoId={id}
      github_url={repo.github_url}
    />
  );
}
