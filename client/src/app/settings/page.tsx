/**
 * User settings route -- the account, the AI credential, the free-tier
 * allowance, the agent settings and MCP access.
 * @module SettingsPage
 */
import { listMcpTokens } from "@/actions/mcpTokens";
import GetMyData from "@/api/auth";
import { getRepositories } from "@/api/repository";
import AgentSettings from "@/components/AgentSettings";
import AiSettings from "@/components/AiSettings";
import DeleteAccount from "@/components/DeleteAccount";
import McpSettings from "@/components/McpSettings";
import Navbar from "@/components/Navbar";
import SettingsSection from "@/components/ui/SettingsSection";
import type User from "@/types/user";

/**
 * The month and year an account was created, e.g. "Mar 2026".
 *
 * @param createdAt - The account's creation timestamp, when the server sent one.
 * @returns The label, or null when there is no usable date.
 */
function memberSince(createdAt: string | null | undefined): string | null {
  if (!createdAt) return null;
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
}

/**
 * A count with its noun, singular or plural.
 *
 * @param n - The count.
 * @param one - The noun for exactly one.
 * @param many - The noun for any other count.
 * @returns E.g. "1 token" or "6 repositories".
 */
function plural(n: number, one: string, many: string): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

/** Up to two initials for the avatar fallback. */
function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? [parts[0], parts[parts.length - 1]] : parts;
  return letters.map((part) => part[0]?.toUpperCase() ?? "").join("") || "?";
}

/** One allowance bar: what has been spent of the server's free tier. */
function Allowance({
  label,
  used,
  limit,
}: {
  label: string;
  used: number;
  limit: number;
}) {
  const spent = Math.min(used, limit);
  const exhausted = limit > 0 && spent >= limit;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex justify-between gap-3 text-sm">
        <span>{label}</span>
        <span
          className={`font-pixel text-xs ${exhausted ? "text-(--accent)" : "text-(--muted-foreground)"}`}
        >
          {spent} / {limit} used
        </span>
      </div>
      <span aria-hidden="true" className="block h-1.5 bg-zinc-900">
        <span
          className={`block h-1.5 ${exhausted ? "bg-(--accent)" : "bg-(--chart-2)"}`}
          style={{ width: limit > 0 ? `${(spent / limit) * 100}%` : "0%" }}
        />
      </span>
    </div>
  );
}

/** The signed-in account, as the server knows it. */
function AccountCard({ user }: { user: User }) {
  return (
    <div className="flex flex-wrap items-center gap-4.5 rounded-md border border-(--border) bg-(--card) p-5">
      {user.avatar_url ? (
        // A remote avatar from GitHub; the image optimiser adds nothing at 56px.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={user.avatar_url}
          alt=""
          width={56}
          height={56}
          className="size-14 rounded-xs object-cover"
        />
      ) : (
        <span
          aria-hidden="true"
          className="flex size-14 items-center justify-center bg-(--primary) font-pixel text-[22px] text-pink-50"
        >
          {initialsOf(user.name)}
        </span>
      )}
      <span className="flex min-w-0 grow flex-col gap-1">
        <span className="truncate text-[17px]">{user.name}</span>
        <span className="truncate text-sm text-(--muted-foreground)">
          {user.email}
        </span>
      </span>
      <span
        className={`inline-flex items-center gap-2 font-pixel text-xs tracking-[0.06em] uppercase ${
          user.github_id ? "text-(--muted-foreground)" : "text-zinc-500"
        }`}
      >
        <span
          aria-hidden="true"
          className={`size-1.75 ${user.github_id ? "bg-(--success)" : "bg-zinc-600"}`}
        />
        {user.github_id ? "GitHub · connected" : "GitHub · not linked"}
      </span>
      {memberSince(user.created_at) && (
        <span className="basis-full font-pixel text-[11px] tracking-[0.08em] text-(--faint-foreground) uppercase">
          Member since {memberSince(user.created_at)}
        </span>
      )}
    </div>
  );
}

/**
 * Server-rendered settings page that fetches the user once and hands the
 * row to the client forms. The MCP token list is fetched here too and seeds
 * the MCP section, which is left out when the server has MCP switched off.
 *
 * @returns Settings layout with navbar and one section per concern.
 */
export default async function Settings() {
  const user = await GetMyData();
  // A failure to list tokens must not take the rest of the settings page down.
  // Nothing is fetched when the server has switched MCP off.
  const [mcpTokens, repositories] = await Promise.all([
    user.mcp_enabled ? listMcpTokens().catch(() => null) : Promise.resolve(null),
    // Only counted for the danger zone, so a failure just leaves the count out.
    getRepositories().catch(() => null),
  ]);
  const footprint = [
    repositories && plural(repositories.length, "repository", "repositories"),
    mcpTokens && plural(mcpTokens.length, "token", "tokens"),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div>
      <Navbar userData={user} />

      <main className="mx-auto flex w-full max-w-260 flex-col px-4 pt-11 pb-16 sm:px-6">
        <header className="flex flex-col gap-3 pb-8">
          <p
            aria-hidden="true"
            className="m-0 font-pixel text-[13px] tracking-[0.12em] text-(--muted-foreground)"
          >
            &gt; illume whoami<span className="caret text-(--accent)">_</span>
          </p>
          <h1 className="m-0 font-pixel text-[clamp(2.4rem,5vw,4rem)] leading-none font-normal tracking-[-0.02em]">
            Your <span className="gradient-text pb-[0.06em]">settings</span>
          </h1>
        </header>

        <SettingsSection
          id="settings-account"
          title="Account"
          description="Illume reads only the repositories you add."
        >
          <AccountCard user={user} />
        </SettingsSection>

        <SettingsSection
          id="settings-ai"
          title="AI provider"
          description="Bring your own key to lift the free-tier limits. It powers the glossary, the reading order, the architecture brief and chat answers. Embeddings stay on the server so the search index stays consistent."
        >
          <AiSettings user={user} />
        </SettingsSection>

        {!user.has_ai_key && (
          <SettingsSection
            id="settings-free-tier"
            title="Free tier"
            description="What the server's key covers. A key of your own removes these limits."
          >
            <div className="flex flex-col gap-4.5 rounded-md border border-(--border) bg-(--card) p-5">
              <Allowance
                label="Repositories"
                used={user.free_ingestions_used}
                limit={user.free_ingestions_limit}
              />
              <Allowance
                label="Chat questions"
                used={user.free_chat_messages_used}
                limit={user.free_chat_messages_limit}
              />
            </div>
          </SettingsSection>
        )}

        <SettingsSection
          id="settings-agent"
          title="Agent"
          description="How much the agent may read in one model call. Larger windows read more before answering and cost more."
        >
          <AgentSettings user={user} />
        </SettingsSection>

        {user.mcp_enabled && (
          <SettingsSection
            id="settings-mcp"
            title="MCP access"
            description="Let Claude Code, Cursor or another AI tool ask Illume about your repositories. Each token can be revoked on its own."
          >
            <McpSettings
              initialTokens={mcpTokens ?? []}
              loadFailed={mcpTokens === null}
            />
          </SettingsSection>
        )}

        <SettingsSection
          id="settings-danger"
          title="Danger zone"
          tone="danger"
          description="This cannot be undone."
        >
          <DeleteAccount email={user.email} footprint={footprint || undefined} />
        </SettingsSection>
      </main>
    </div>
  );
}
