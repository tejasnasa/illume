import { getRepoGraph } from "@/api/graph";
import { GetRepository } from "@/api/repository";
import AnimatedLayout from "@/components/AnimatedLayout";
import BackgroundGraph from "@/components/BackgroundGraph";
import RepoNavbar from "@/components/RepoNavbar";
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
  
  let graph = null;
  try {
    if (repo.status === "ready") {
      graph = await getRepoGraph(repo.id, "file");
    }
  } catch (error) {
    console.error("Failed to fetch graph for background:", error);
  }

  return (
    <main className="relative min-h-screen">
      <BackgroundGraph graph={graph} />
      <RepoNavbar name={repo.name} id={Number(id)} status={repo.status} />

      <AnimatedLayout>{children}</AnimatedLayout>
    </main>
  );
}
