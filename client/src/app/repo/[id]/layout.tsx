import { getRepoGraph } from "@/api/graph";
import { GetRepository } from "@/api/repository";
import AnimatedLayout from "@/components/AnimatedLayout";
import BackgroundGraph from "@/components/BackgroundGraph";
import type { Metadata, ResolvingMetadata } from "next";

type Props = {
  params: Promise<{ id: string }>;
};

export async function generateMetadata(
  { params }: Props,
  parent: ResolvingMetadata,
): Promise<Metadata> {
  const { id } = await params;

  const repo = await GetRepository(Number(id));

  return {
    title: `${repo.name} - Illume`,
  };
}

export default async function RootLayout({
  children,
  params,
}: Readonly<{
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}>) {
  const { id } = await params;
  const repo = await GetRepository(Number(id));
  const graph = await getRepoGraph(repo.id, "file");

  return (
    <main className="relative min-h-screen">
      <BackgroundGraph graph={graph} />

      <AnimatedLayout>{children}</AnimatedLayout>
    </main>
  );
}
