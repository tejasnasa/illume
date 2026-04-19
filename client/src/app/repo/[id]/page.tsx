import { GetRepository } from "@/api/repository";

export default async function Repository({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const repo = await GetRepository(Number(id));

  return (
    <main>
      <div className="bg-(--card)/10 text-xl backdrop-blur-xs border rounded-sm p-4">
        <h2>{repo.name}</h2>
      </div>
    </main>
  );
}
