import { getRepoGraph } from "@/api/graph";
import { GetRepository } from "@/api/repository";
import BackgroundGraph from "@/components/BackgroundGraph";

export default async function Repository({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const repo = await GetRepository(Number(id));
  const graph = await getRepoGraph(repo.id, "file");

  return (
    <main className="relative min-h-screen flex items-center">
      <BackgroundGraph graph={graph} />

      <div className="bg-(--card)/10 text-xl backdrop-blur-xs border rounded-sm p-4">
        <h2>{repo.name}</h2>
      </div>
    </main>
  );
}
