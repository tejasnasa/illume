import { getRepoGraph } from "@/api/graph";
import BackgroundGraph from "@/components/BackgroundGraph";

export default async function Repository({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  const graph = await getRepoGraph(id, "file");

  return (
    <main className="relative min-h-screen flex items-center justify-center">
      <BackgroundGraph graph={graph} />

      <div className="bg-(--card)/50 text-xl backdrop-blur-xs border rounded-sm p-4">
        <h1 className="text-(--foreground)">Hello</h1>
      </div>
    </main>
  );
}
