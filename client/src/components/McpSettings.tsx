/**
 * MCP settings -- access tokens and the snippets that connect an AI tool.
 * @module McpSettings
 */
"use client";

import { createMcpToken, revokeMcpToken } from "@/actions/mcpTokens";
import type { McpToken, McpTokenExpiry } from "@/types/mcp";
import { useState } from "react";
import Button from "./ui/Button";
import Input from "./ui/Input";
import Select from "./ui/Select";

/** Shown in the snippets whenever no fresh token is on screen. */
const TOKEN_PLACEHOLDER = "<your token>";

/** The launcher package, run through `uvx`. */
const LAUNCHER_SOURCE =
  "git+https://github.com/tejasnasa/illume#subdirectory=mcp-local";

const EXPIRY_OPTIONS = [
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "never", label: "Never" },
] as const;

type SnippetTab =
  "claude-code" | "cursor" | "vscode" | "codex" | "opencode" | "launcher";

const TABS: { id: SnippetTab; label: string }[] = [
  { id: "claude-code", label: "Claude Code" },
  { id: "cursor", label: "Cursor" },
  { id: "vscode", label: "VS Code" },
  { id: "codex", label: "Codex" },
  { id: "opencode", label: "OpenCode" },
  { id: "launcher", label: "Local launcher" },
];

/** Where each snippet goes, shown above it. */
const TAB_HINTS: Record<SnippetTab, string> = {
  "claude-code": "Run this in a terminal.",
  cursor: "Add this to ~/.cursor/mcp.json, or .cursor/mcp.json in a project.",
  vscode: "Add this to .vscode/mcp.json in your workspace.",
  codex:
    "Add this to ~/.codex/config.toml, and export the token in the environment Codex runs in. The config names the variable, not the token.",
  opencode:
    "Add this to opencode.jsonc in your project, or ~/.config/opencode/opencode.jsonc for every project, and export the token in the environment OpenCode runs in.",
  launcher:
    "For clients that cannot send custom headers, such as Claude Desktop: add this to the mcpServers section of its config file. The token stays in the environment, not on a command line.",
};

/**
 * Props for the McpSettings component.
 */
type Props = {
  /** The user's active tokens, fetched on the server. */
  initialTokens: McpToken[];
  /** Whether fetching the list failed, so an empty list may not be the truth. */
  loadFailed?: boolean;
};

/**
 * Formats an ISO timestamp as a short calendar date.
 *
 * @param iso - ISO timestamp from the API.
 * @returns The date in the viewer's locale.
 */
function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * Builds the snippet for one client.
 *
 * @param tab - Which client the snippet is for.
 * @param url - The MCP endpoint.
 * @param token - A fresh plaintext token, or the placeholder.
 * @returns The text to copy.
 */
function buildSnippet(tab: SnippetTab, url: string, token: string) {
  const header = `Bearer ${token}`;
  switch (tab) {
    case "claude-code":
      return `claude mcp add --transport http illume ${url} --header "Authorization: ${header}"`;
    case "cursor":
      return JSON.stringify(
        { mcpServers: { illume: { url, headers: { Authorization: header } } } },
        null,
        2,
      );
    case "vscode":
      return JSON.stringify(
        {
          servers: {
            illume: { type: "http", url, headers: { Authorization: header } },
          },
        },
        null,
        2,
      );
    case "codex":
      return [
        `# export ILLUME_MCP_TOKEN="${token}"`,
        "[mcp_servers.illume]",
        `url = "${url}"`,
        'bearer_token_env_var = "ILLUME_MCP_TOKEN"',
      ].join("\n");
    case "opencode":
      return [
        `// export ILLUME_MCP_TOKEN="${token}"`,
        JSON.stringify(
          {
            $schema: "https://opencode.ai/config.json",
            mcp: {
              servers: {
                illume: {
                  type: "remote",
                  url,
                  oauth: false,
                  headers: { Authorization: "Bearer {env:ILLUME_MCP_TOKEN}" },
                },
              },
            },
          },
          null,
          2,
        ),
      ].join("\n");
    case "launcher":
      return JSON.stringify(
        {
          mcpServers: {
            illume: {
              command: "uvx",
              args: ["--from", LAUNCHER_SOURCE, "illume-mcp"],
              env: { ILLUME_MCP_TOKEN: token },
            },
          },
        },
        null,
        2,
      );
  }
}

/**
 * Renders the MCP card: the token list, the create form, and the connection
 * snippets.
 *
 * A created token's plaintext lives only in component state while the notice
 * is open; dismissing it drops the value and the snippets fall back to a
 * placeholder.
 *
 * @param initialTokens - Active tokens seeding the list.
 * @param loadFailed - Whether the list could not be fetched.
 * @returns The rendered MCP settings card.
 */
export default function McpSettings({
  initialTokens,
  loadFailed = false,
}: Props) {
  const [tokens, setTokens] = useState(initialTokens);
  const [name, setName] = useState("");
  const [expiry, setExpiry] = useState<string>("90");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [fresh, setFresh] = useState<string | null>(null);
  const [copied, setCopied] = useState<"token" | "snippet" | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const [tab, setTab] = useState<SnippetTab>("claude-code");

  const url = `${process.env.NEXT_PUBLIC_BACKEND_URL}/mcp`;
  const snippet = buildSnippet(tab, url, fresh ?? TOKEN_PLACEHOLDER);

  /** Creates the token and holds its plaintext until dismissed. */
  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setCreateError("Give the token a name.");
      return;
    }
    setCreateError(null);
    setCreating(true);
    try {
      const expiresInDays: McpTokenExpiry =
        expiry === "never" ? null : (Number(expiry) as 30 | 90);
      const { token, ...created } = await createMcpToken({
        name: trimmed,
        expiresInDays,
      });
      setTokens((current) => [created, ...current]);
      setFresh(token);
      setCopied(null);
      setName("");
    } catch (err) {
      setCreateError(
        err instanceof Error ? err.message : "Failed to create token.",
      );
    } finally {
      setCreating(false);
    }
  }

  /** Revokes a confirmed token and removes its row. */
  async function handleRevoke(id: string) {
    setRevoking(id);
    setRevokeError(null);
    try {
      await revokeMcpToken(id);
      setTokens((current) => current.filter((token) => token.id !== id));
      setConfirming(null);
    } catch (err) {
      setRevokeError(
        err instanceof Error ? err.message : "Failed to revoke token.",
      );
    } finally {
      setRevoking(null);
    }
  }

  /** Copies text and flags which control did it. */
  async function copy(text: string, what: "token" | "snippet") {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(what);
    } catch {
      // Clipboard unavailable; the text stays selectable in the field.
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-col rounded-md border border-(--border) bg-(--card)">
        <p className="eyebrow m-0 border-b border-white/8 px-4.5 py-3.5">
          Tokens · {tokens.length}
        </p>

        {fresh && (
          <div
            role="status"
            className="rise mx-4.5 mt-3.5 flex flex-col gap-2.5 rounded-sm border border-(--accent)/40 bg-(--accent)/5 p-3.5"
          >
            <p className="m-0 font-pixel text-[11px] tracking-[0.08em] text-(--accent) uppercase">
              Copy your token now, you won&apos;t see this again.
            </p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                readOnly
                aria-label="New token"
                value={fresh}
                onFocus={(event) => event.currentTarget.select()}
                className="min-w-0 flex-1 font-pixel"
              />
              <Button
                type="button"
                size="sm"
                className="h-11"
                onClick={() => copy(fresh, "token")}
              >
                {copied === "token" ? "Copied" : "Copy token"}
              </Button>
            </div>
            <div className="flex justify-end">
              <Button
                type="button"
                size="xs"
                variant="ghost"
                onClick={() => {
                  setFresh(null);
                  setCopied(null);
                }}
              >
                Done
              </Button>
            </div>
          </div>
        )}

        {tokens.length === 0 ? (
          <p className="m-0 px-4.5 py-4 text-sm text-(--muted-foreground)">
            {loadFailed
              ? "Your tokens could not be loaded. Reload the page to try again."
              : "No tokens yet. Create one below."}
          </p>
        ) : (
          <ul className="m-0 flex list-none flex-col p-2">
            {tokens.map((token) => (
              <li
                key={token.id}
                className="flex flex-col justify-between gap-2 rounded-sm p-2.5 hover:bg-zinc-900 sm:flex-row sm:items-center"
              >
                <div className="flex min-w-0 flex-col gap-0.5">
                  <p className="m-0 text-sm break-all">
                    {token.name}{" "}
                    <span className="font-pixel text-xs text-zinc-500">
                      ilm_{token.prefix}…
                    </span>
                  </p>
                  <p className="m-0 font-pixel text-[11px] tracking-[0.05em] text-zinc-500 uppercase">
                    Created {formatDate(token.created_at)} · Last used{" "}
                    {token.last_used_at
                      ? formatDate(token.last_used_at)
                      : "never"}{" "}
                    · Expires{" "}
                    {token.expires_at ? formatDate(token.expires_at) : "never"}
                  </p>
                </div>

                {confirming === token.id ? (
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    <span className="text-xs text-zinc-300">
                      Revoke this token?
                    </span>
                    <Button
                      type="button"
                      size="xs"
                      variant="danger"
                      loading={revoking === token.id}
                      onClick={() => handleRevoke(token.id)}
                    >
                      Confirm revoke
                    </Button>
                    <Button
                      type="button"
                      size="xs"
                      variant="ghost"
                      onClick={() => setConfirming(null)}
                    >
                      Cancel
                    </Button>
                  </div>
                ) : (
                  <Button
                    type="button"
                    size="xs"
                    variant="ghost"
                    className="shrink-0 self-start sm:self-auto"
                    aria-label={`Revoke ${token.name}`}
                    onClick={() => {
                      setRevokeError(null);
                      setConfirming(token.id);
                    }}
                  >
                    Revoke
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        {revokeError && (
          <p role="alert" className="m-0 px-4.5 pb-3 text-xs text-red-400">
            {revokeError}
          </p>
        )}

        <form
          onSubmit={handleCreate}
          noValidate
          className="flex flex-col gap-3 border-t border-white/8 px-4.5 py-4 sm:flex-row sm:items-end"
        >
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <label
              htmlFor="mcp-token-name"
              className="font-pixel text-[11px] tracking-[0.12em] text-(--muted-foreground) uppercase"
            >
              Token name
            </label>
            <Input
              id="mcp-token-name"
              type="text"
              maxLength={60}
              autoComplete="off"
              placeholder="Laptop Claude Code"
              value={name}
              aria-invalid={Boolean(createError)}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="sm:w-40">
            <Select
              id="mcp-token-expiry"
              label="Expires"
              value={expiry}
              onChange={setExpiry}
              options={EXPIRY_OPTIONS}
            />
          </div>
          <Button type="submit" size="md" loading={creating} className="h-11">
            <span aria-hidden="true">+</span> New token
          </Button>
        </form>
        {createError && (
          <p role="alert" className="m-0 px-4.5 pb-4 text-xs text-red-400">
            {createError}
          </p>
        )}
      </div>

      <div className="flex flex-col overflow-hidden rounded-md border border-(--border) bg-(--card)">
        <div
          role="tablist"
          aria-label="Client"
          className="flex flex-wrap border-b border-white/8 px-2"
        >
          {TABS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => {
                setTab(id);
                setCopied((current) =>
                  current === "snippet" ? null : current,
                );
              }}
              className={`cursor-pointer px-3 py-3 font-pixel text-xs tracking-[0.06em] transition-colors ${
                tab === id
                  ? "text-(--foreground) shadow-[inset_0_-2px_0_var(--accent)]"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="m-0 px-4.5 pt-3.5 text-[13px] text-(--muted-foreground)">
          {TAB_HINTS[tab]}
        </p>
        <div className="relative m-4.5 mt-3">
          <pre
            data-testid="mcp-snippet"
            className="custom-scrollbar m-0 overflow-x-auto rounded-sm border border-white/8 bg-[#060608] p-4 pr-32 font-pixel text-xs leading-[1.7] whitespace-pre text-zinc-300"
          >
            {snippet}
          </pre>
          <Button
            type="button"
            size="xs"
            variant="ghost"
            className="absolute top-2 right-2 bg-(--card)"
            onClick={() => copy(snippet, "snippet")}
          >
            {copied === "snippet" ? "Copied" : "Copy snippet"}
          </Button>
        </div>
        <p className="m-0 border-t border-white/6 px-4.5 py-3.5 text-xs leading-relaxed text-zinc-500">
          The AI tool will read text from your repositories, including commit
          messages and PR descriptions written by others, so treat its
          suggestions to run commands with the usual care. A token reads private
          code, so keep its expiry short.
        </p>
      </div>
    </div>
  );
}
