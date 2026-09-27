/**
 * Repository overview with architecture summary, tech stack, and chat.
 * @module RepositoryPage
 */
import GetMyData from "@/api/auth";
import { GetGuide } from "@/api/guide";
import { GetRepository } from "@/api/repository";
import Chat from "@/components/Chat";
import IngestFlow from "@/components/IngestFlow";
import { timeAgo } from "@/utils/timeAgo";
import {
  AtomIcon,
  CheckCircleIcon,
  CodeIcon,
  DatabaseIcon,
  GitBranchIcon,
  GithubLogoIcon,
  LinkIcon,
  TreeStructureIcon,
  WrenchIcon,
} from "@phosphor-icons/react/dist/ssr";
import { cookies } from "next/headers";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Server-rendered overview: chat when ready, live logs while indexing.
 *
 * @param params - Route params promise resolving to the repository id.
 * @returns Repository overview with summary, stack, and chat/logs panels.
 */
export default async function Repository({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const repo = await GetRepository(Number(id));

  const isReady = repo.status === "ready";

  // Guide is only available after indexing; live logs need the auth token.
  const guide = isReady ? await GetGuide(repo.id) : null;

  const cookieStore = await cookies();
  const token = cookieStore.get("access_token")?.value || "";

  // While indexing there is nothing to summarise yet, so the whole page
  // becomes the live progress view. Returning early also skips the quota
  // round trip below, which only the chat composer needs.
  if (!isReady) {
    return (
      <IngestFlow
        repoId={repo.id}
        token={token}
        repoLabel={repo.github_url.split("github.com/")[1]}
        branch={repo.ingested_branch}
        commitSha={repo.ingested_commit_sha}
        status={repo.status}
      />
    );
  }

  /**
   * Resolves the chat quota so the composer can disable itself before any
   * request goes out. The backend exposes the user's free-tier counter on
   * /me; for a BYOK user the count is irrelevant (`null` in the panel), so the
   * gate only fires for keyless users and after the allowance is spent.
   *
   * Wrapped in a try/catch because /me is unrelated to the page load -- a
   * transient failure here must not block rendering. The chat composer is the
   * one place the count is consumed today, and it falls back to `null`
   * (unknown), which behaves as "do not disable".
   */
  let freeChatRemaining: number | null = null;
  try {
    const me = await GetMyData();
    if (!me.has_ai_key) {
      freeChatRemaining = Math.max(0, 5 - me.free_chat_messages_used);
    }
  } catch {
    // Leave the count unknown; the chat composer remains enabled.
  }

  return (
    <main className="p-4 h-[calc(100vh-64px)] flex gap-4 max-w-7xl mx-auto">
      <section className="w-1/2 flex flex-col gap-4 h-full">
        <div className="grid grid-cols-2 gap-4 h-30 shrink-0">
          <Link
            href={repo.github_url}
            target="_blank"
            className="group relative glass-card rounded-sm overflow-hidden hover:border-(--primary)/50 transition-colors"
          >
            <div className="absolute inset-0 bg-linear-to-br from-(--primary)/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
            <div className="absolute top-4 right-4 text-(--muted-foreground) group-hover:text-(--foreground) transition-colors">
              <LinkIcon size={20} />
            </div>
            <div className="p-4 flex flex-col justify-between h-full">
              <div className="flex justify-between items-start">
                <span className="text-xs font-semibold uppercase tracking-wider text-(--muted-foreground)">
                  Repository
                </span>
                {repo.ingested_branch && (
                  <span className="text-[10px] font-mono bg-(--primary)/10 text-(--primary) px-2 py-0.5 rounded border border-(--primary)/20 flex items-center gap-1 shrink-0">
                    <GitBranchIcon size={12} />
                    {repo.ingested_branch}
                    {repo.ingested_commit_sha && (
                      <span className="opacity-75">
                        @{repo.ingested_commit_sha.substring(0, 7)}
                      </span>
                    )}
                  </span>
                )}
              </div>
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

          <div className="glass-card rounded-sm p-4 flex flex-col justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-(--muted-foreground)">
              Processing Status
            </span>
            <div className="flex items-end justify-between">
              <div>
                {/* Reaching this card means the repository is indexed, so the
                    status is always the terminal one here. */}
                <div className="flex items-center gap-2 font-bold text-xl uppercase text-(--success)">
                  <CheckCircleIcon size={24} weight="fill" />
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

        <>
          <div className="glass-card rounded-sm p-4 flex-1 min-h-0 flex flex-col relative overflow-hidden animate-fade-in">
            <h2 className="text-lg font-bold mb-4 text-(--foreground) flex items-center gap-2 shrink-0">
              <TreeStructureIcon size={20} className="text-(--primary)" />
              AI Architecture Overview
            </h2>
            {repo.architecture_summary ? (
              <div className="overflow-y-auto custom-scrollbar pr-2.5 text-sm text-(--muted-foreground) leading-relaxed text-justify prose prose-sm dark:prose-invert">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {repo.architecture_summary}
                </ReactMarkdown>
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center text-(--muted-foreground) text-sm italic">
                No architecture summary generated.
              </div>
            )}
          </div>

          <div className="glass-card rounded-sm p-4 shrink-0 flex flex-col animate-fade-in">
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
                          className="px-2 py-0.5 bg-(--destructive)/10 text-(--destructive) border border-(--destructive)/20 text-[10px] font-mono"
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
                          className="px-2 py-0.5 bg-(--chart-1)/10 text-(--chart-1) border border-(--chart-1)/20 text-[10px] font-mono"
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
                          className="px-2 py-0.5 bg-(--chart-1)/10 text-(--chart-1) border border-(--chart-1)/20 text-[10px] font-mono"
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
                  <DatabaseIcon size={12} /> Infrastructure
                </h3>
                {repo.detected_stack?.infrastructure?.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {repo.detected_stack.infrastructure?.map(
                      (tool: string, i: number) => (
                        <span
                          key={i}
                          className="px-2 py-0.5 bg-(--chart-1)/10 text-(--chart-1) border border-(--chart-1)/20 text-[10px] font-mono"
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
                          className="px-2 py-0.5 bg-(--chart-1)/10 text-(--chart-1) border border-(--chart-1)/20 text-[10px] font-mono"
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
                <h3 className="text-[10px] font-bold uppercase tracking-widest text-(--primary) mb-1.5 flex items-center gap-1.5">
                  <DatabaseIcon size={12} /> External
                </h3>
                {(guide?.architecture_brief?.external_integrations?.length ??
                  0) > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {guide?.architecture_brief?.external_integrations?.map(
                      (tool: string, i: number) => (
                        <span
                          key={i}
                          className="px-2 py-0.5 bg-(--chart-1)/10 text-(--chart-1) border border-(--chart-1)/20 text-[10px] font-mono"
                        >
                          {tool.charAt(0).toUpperCase() + tool.slice(1)}
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
      </section>

      <section className="w-1/2 h-full flex flex-col glass-card rounded-sm overflow-hidden border border-(--border)">
        <Chat
          repoId={repo.id}
          url={repo.github_url}
          branch={repo.ingested_branch}
          freeChatRemaining={freeChatRemaining}
        />
      </section>
    </main>
  );
}
