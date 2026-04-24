import { GetRepository } from "@/api/repository";
import Chat from "@/components/Chat";
import TerminalLogs from "@/components/TerminalLogs";
import Skeleton from "@/components/ui/Skeleton";
import { timeAgo } from "@/utils/timeAgo";
import {
  AtomIcon,
  CheckCircleIcon,
  CodeIcon,
  DatabaseIcon,
  GitBranchIcon,
  GithubLogoIcon,
  LinkIcon,
  SpinnerIcon,
  TreeStructureIcon,
  WrenchIcon,
} from "@phosphor-icons/react/dist/ssr";
import { cookies } from "next/headers";
import Link from "next/link";

export default async function Repository({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const repo = await GetRepository(Number(id));

  const isReady = repo.status === "ready";

  const cookieStore = await cookies();
  const token = cookieStore.get("access_token")?.value || "";

  return (
    <main className="p-4 h-[calc(100vh-64px)] flex gap-4 max-w-7xl mx-auto">
      <section className="w-1/2 flex flex-col gap-4 h-full">
        <div className="grid grid-cols-2 gap-4 h-30 shrink-0">
          <Link
            href={repo.github_url}
            target="_blank"
            className="group relative glass-card overflow-hidden hover:border-(--primary)/50 transition-colors"
          >
            <div className="absolute inset-0 bg-linear-to-br from-(--primary)/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
            <div className="absolute top-4 right-4 text-(--muted-foreground) group-hover:text-(--foreground) transition-colors">
              <LinkIcon size={20} />
            </div>
            <div className="p-4 flex flex-col justify-between h-full">
              <span className="text-xs font-semibold uppercase tracking-wider text-(--muted-foreground)">
                Repository
              </span>
              <h2 className="text-2xl font-bold flex items-center gap-3 text-(--foreground) truncate">
                <GithubLogoIcon
                  size={28}
                  weight="fill"
                  className="text-(--primary) shrink-0"
                />
                <span className="truncate">
                  {repo.github_url.split("github.com/")[1]}
                </span>
              </h2>
            </div>
          </Link>

          <div className="glass-card p-4 flex flex-col justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-(--muted-foreground)">
              Processing Status
            </span>
            <div className="flex items-end justify-between">
              <div>
                <div
                  className={`flex items-center gap-2 font-bold text-xl uppercase ${isReady ? "text-green-500" : "text-yellow-500"}`}
                >
                  {isReady ? (
                    <CheckCircleIcon size={24} weight="fill" />
                  ) : (
                    <SpinnerIcon size={24} className="animate-spin" />
                  )}
                  {repo.status}
                </div>
              </div>
              <div className="text-right text-xs text-(--muted-foreground)">
                <p>Updated: {timeAgo(repo.updated_at)}</p>
                <p className="opacity-60">
                  Created: {timeAgo(repo.created_at)}
                </p>
              </div>
            </div>
          </div>
        </div>

        {!isReady ? (
          <>
            <div className="glass-card p-6 flex-1 min-h-0 flex flex-col border border-(--border) bg-(--secondary)/10">
              <Skeleton className="w-48 h-6 mb-6" />
              <div className="space-y-3 flex-1">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-11/12" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-4/5" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-2/3" />
              </div>
            </div>

            <div className="glass-card p-6 shrink-0 h-40 flex flex-col border border-(--border) bg-(--secondary)/10">
              <Skeleton className="w-32 h-5 mb-4" />
              <div className="grid grid-cols-2 gap-x-8 gap-y-4">
                <div>
                  <Skeleton className="w-20 h-3 mb-2" />
                  <div className="flex gap-2">
                    <Skeleton className="w-12 h-5" />
                    <Skeleton className="w-16 h-5" />
                  </div>
                </div>
                <div>
                  <Skeleton className="w-24 h-3 mb-2" />
                  <div className="flex gap-2">
                    <Skeleton className="w-14 h-5" />
                  </div>
                </div>
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="glass-card p-4 flex-1 min-h-0 flex flex-col relative overflow-hidden animate-fade-in">
              <h2 className="text-lg font-bold mb-4 text-(--foreground) flex items-center gap-2 shrink-0">
                <TreeStructureIcon size={20} className="text-(--primary)" />
                AI Architecture Overview
              </h2>
              {repo.architecture_summary ? (
                <div className="overflow-y-auto custom-scrollbar pr-4 text-sm text-(--muted-foreground) leading-relaxed whitespace-pre-line text-justify">
                  {repo.architecture_summary}
                </div>
              ) : (
                <div className="flex-1 flex items-center justify-center text-(--muted-foreground) text-sm italic">
                  No architecture summary generated.
                </div>
              )}
            </div>

            <div className="glass-card p-4 shrink-0 flex flex-col animate-fade-in">
              <h2 className="text-lg font-bold mb-4 text-(--foreground) flex items-center gap-2 shrink-0">
                <AtomIcon size={20} className="text-(--primary)" />
                Tech Stack Detected
              </h2>
              <div className="flex-1 overflow-y-auto custom-scrollbar pr-2 grid grid-cols-2 gap-x-6 gap-y-3">
                <div>
                  <h3 className="text-[10px] font-bold uppercase tracking-widest text-(--muted-foreground) mb-1.5 flex items-center gap-1.5">
                    <CodeIcon size={12} /> Languages
                  </h3>
                  {repo.detected_stack?.languages?.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {repo.detected_stack.languages.map(
                        (tool: string, i: number) => (
                          <span
                            key={i}
                            className="px-2 py-0.5 rounded bg-(--destructive)/10 text-(--destructive) border border-(--destructive)/20 text-[10px] font-mono"
                          >
                            {tool}
                          </span>
                        ),
                      )}
                    </div>
                  ) : (
                    <span className="text-xs text-(--muted-foreground)/50 italic">
                      None detected
                    </span>
                  )}
                </div>

                <div>
                  <h3 className="text-[10px] font-bold uppercase tracking-widest text-(--muted-foreground) mb-1.5 flex items-center gap-1.5">
                    <WrenchIcon size={12} /> Frameworks
                  </h3>
                  {repo.detected_stack?.frameworks?.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {repo.detected_stack.frameworks.map(
                        (tool: string, i: number) => (
                          <span
                            key={i}
                            className="px-2 py-0.5 rounded bg-(--chart-1)/10 text-(--chart-1) border border-(--chart-1)/20 text-[10px] font-mono"
                          >
                            {tool}
                          </span>
                        ),
                      )}
                    </div>
                  ) : (
                    <span className="text-xs text-(--muted-foreground)/50 italic">
                      None detected
                    </span>
                  )}
                </div>

                <div>
                  <h3 className="text-[10px] font-bold uppercase tracking-widest text-(--muted-foreground) mb-1.5 flex items-center gap-1.5">
                    <DatabaseIcon size={12} /> Databases
                  </h3>
                  {repo.detected_stack?.databases?.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {repo.detected_stack.databases.map(
                        (tool: string, i: number) => (
                          <span
                            key={i}
                            className="px-2 py-0.5 rounded bg-(--chart-1)/10 text-(--chart-1) border border-(--chart-1)/20 text-[10px] font-mono"
                          >
                            {tool}
                          </span>
                        ),
                      )}
                    </div>
                  ) : (
                    <span className="text-xs text-(--muted-foreground)/50 italic">
                      None detected
                    </span>
                  )}
                </div>

                <div>
                  <h3 className="text-[10px] font-bold uppercase tracking-widest text-(--muted-foreground) mb-1.5 flex items-center gap-1.5">
                    <GitBranchIcon size={12} />
                    CI/CD And Infra
                  </h3>
                  {repo.detected_stack?.ci_cd?.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {repo.detected_stack.ci_cd.map(
                        (tool: string, i: number) => (
                          <span
                            key={i}
                            className="px-2 py-0.5 rounded bg-(--chart-1)/10 text-(--chart-1) border border-(--chart-1)/20 text-[10px] font-mono"
                          >
                            {tool}
                          </span>
                        ),
                      )}
                    </div>
                  ) : (
                    <span className="text-xs text-(--muted-foreground)/50 italic">
                      None detected
                    </span>
                  )}
                </div>
              </div>
            </div>
          </>
        )}
      </section>

      <section className="w-1/2 h-full flex flex-col glass-card rounded-2xl overflow-hidden border border-(--border)">
        {isReady ? (
          <Chat repoId={repo.id} url={repo.github_url} />
        ) : (
          <TerminalLogs repoId={repo.id} token={token} />
        )}
      </section>
    </main>
  );
}
