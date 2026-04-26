import { getRepoGraph } from "@/api/graph";
import { GetRepository } from "@/api/repository";
import AnimatedLayout from "@/components/AnimatedLayout";
import BackgroundGraph from "@/components/BackgroundGraph";
import RepoNavbar from "@/components/RepoNavbar";
import RepoNavSkel from "@/components/ui/RepoNavSkel";
import type { Metadata, ResolvingMetadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

type Props = {
  params: Promise<{ id: string }>;
};

export async function generateMetadata(
  { params }: Props,
  parent: ResolvingMetadata,
): Promise<Metadata> {
  const { id } = await params;

  try {
    const repo = await GetRepository(Number(id));
    return {
      title: `${repo.name} - Illume`,
    };
  } catch {
    return {
      title: "Not Found - Illume",
    };
  }
}

export default async function RootLayout({
  children,
  params,
}: Readonly<{
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}>) {
  const { id } = await params;
  let repo;
  try {
    repo = await GetRepository(Number(id));
  } catch {
    notFound();
  }

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
      <Suspense fallback={<RepoNavSkel />}>
        <RepoNavbar
          name={repo.name}
          num_id={Number(id)}
          id={repo.id}
          status={repo.status}
        />
      </Suspense>

      <AnimatedLayout>{children}</AnimatedLayout>
    </main>
  );
}
