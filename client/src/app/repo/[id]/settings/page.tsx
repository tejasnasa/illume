/**
 * Repository settings route.
 * @module RepoSettingsPage
 */
import { GetRepository } from "@/api/repository";
import RepoSettings from "@/components/RepoSettings";
import { redirect } from "next/navigation";

/**
 * Server-rendered settings page for one repository.
 *
 * Settings act on an analysed repository, so while it is still being read
 * the route sends the user back to the live ingest view instead.
 *
 * @param params - Route params promise resolving to the repository number.
 * @returns The settings page.
 */
export default async function RepoSettingsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const repo = await GetRepository(Number(id));
  if (repo.status !== "ready" && repo.status !== "failed") redirect(`/repo/${id}`);

  return (
    <div className="mx-auto flex w-full max-w-260 flex-col px-4 pt-11 pb-16 sm:px-6">
      <header className="flex flex-col gap-3 pb-8">
        <p
          aria-hidden="true"
          className="m-0 font-pixel text-[13px] tracking-[0.12em] text-(--muted-foreground)"
        >
          &gt; illume config<span className="caret text-(--accent)">_</span>
        </p>
        <h1 className="m-0 font-pixel text-[clamp(2.4rem,5vw,4rem)] leading-none font-normal tracking-[-0.02em]">
          Repository <span className="gradient-text">settings</span>
        </h1>
      </header>
      <RepoSettings repo={repo} />
    </div>
  );
}
