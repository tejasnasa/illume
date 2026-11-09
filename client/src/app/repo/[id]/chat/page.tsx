/**
 * Fullscreen repository chat with presets, a live activity block and graph.
 * @module ChatRoute
 */
import GetMyData from "@/api/auth";
import { GetGuide } from "@/api/guide";
import { GetRepository } from "@/api/repository";
import ChatPage from "@/components/chat/ChatPage";
import type { Capabilities } from "@/lib/agent/presets";
import { buildSuggestions } from "@/lib/agent/suggestions";
import { redirect } from "next/navigation";

/**
 * Server-rendered shell: resolves the repository, the account's capabilities
 * and the starter questions, then hands over to the client chat.
 *
 * @param params - Route params promise resolving to the repository number.
 * @returns The chat page, or a redirect home while the repository is indexing.
 */
export default async function ChatRoute({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const repo = await GetRepository(Number(id));

  if (repo.status !== "ready") redirect(`/repo/${id}`);

  let criticalFile: string | null = null;
  try {
    const guide = await GetGuide(repo.id);
    criticalFile = guide.critical_files?.[0]?.file_path ?? null;
  } catch {
    // Suggestions fall back to generic questions without the guide.
  }

  let caps: Capabilities = { hasOwnKey: false, supportsTools: null };
  let freeChatRemaining: number | null = null;
  try {
    const me = await GetMyData();
    caps = {
      hasOwnKey: me.has_ai_key,
      supportsTools: me.ai_supports_tools ?? null,
    };
    if (!me.has_ai_key) {
      freeChatRemaining = Math.max(
        0,
        me.free_chat_messages_limit - me.free_chat_messages_used,
      );
    }
  } catch {
    // /me is unrelated to rendering; without it the free tier is assumed and
    // the quota stays unknown, which leaves the composer enabled.
  }

  return (
    <ChatPage
      repoId={repo.id}
      repoName={repo.name}
      url={repo.github_url}
      commitSha={repo.ingested_commit_sha}
      branch={repo.ingested_branch}
      suggestions={buildSuggestions({
        name: repo.name,
        entryPoints: repo.entry_points,
        criticalFile,
      })}
      caps={caps}
      freeChatRemaining={freeChatRemaining}
    />
  );
}
