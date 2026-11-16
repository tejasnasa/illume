/**
 * MCP settings -- access tokens and the snippets that connect an AI tool.
 * @module McpSettings
 */
"use client";

import { createMcpToken, revokeMcpToken } from "@/actions/mcpTokens";
import type { McpToken, McpTokenExpiry } from "@/types/mcp";
import {
  CheckIcon,
  CopyIcon,
  KeyIcon,
  PlusIcon,
  TrashIcon,
} from "@phosphor-icons/react/dist/ssr";
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

type SnippetTab = "claude-code" | "cursor" | "vscode" | "launcher";

const TABS: { id: SnippetTab; label: string }[] = [
  { id: "claude-code", label: "Claude Code" },
  { id: "cursor", label: "Cursor" },
  { id: "vscode", label: "VS Code" },
  { id: "launcher", label: "Local launcher" },
];

/** Where each snippet goes, shown above it. */
const TAB_HINTS: Record<SnippetTab, string> = {
  "claude-code": "Run this in a terminal.",
  cursor: "Add this to ~/.cursor/mcp.json, or .cursor/mcp.json in a project.",
  vscode: "Add this to .vscode/mcp.json in your workspace.",
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
    <div className="rounded-sm border border-(--primary)/20 divide-y divide-(--primary)/10 p-2">
      <div className="px-5 py-3">
        <p className="text-xs font-semibold uppercase tracking-widest text-(--primary)">
          MCP access
        </p>
      </div>

      <div className="px-5 py-4 space-y-4">
        <p className="text-xs text-(--muted-foreground)">
          Tokens let an AI tool such as Claude Code or Cursor read your
          repositories and ask Illume questions.
        </p>

        {fresh && (
          <div
            role="status"
            className="rounded-sm border border-(--primary)/30 p-4 space-y-2"
          >
            <p className="text-sm">
              Copy your token now, you won&apos;t see this again.
            </p>
            <div className="flex flex-col sm:flex-row gap-2">
              <Input
                readOnly
                aria-label="New token"
                value={fresh}
                onFocus={(event) => event.currentTarget.select()}
                className="flex-1 min-w-0 font-mono"
              />
              <Button
                type="button"
                size="sm"
                className="gap-1.5"
                onClick={() => copy(fresh, "token")}
              >
                {copied === "token" ? (
                  <CheckIcon size={15} />
                ) : (
                  <CopyIcon size={15} />
                )}
                {copied === "token" ? "Copied" : "Copy token"}
              </Button>
            </div>
            <div className="flex justify-end">
              <Button
                type="button"
                size="xs"
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
          <p className="text-sm text-(--muted-foreground)">
            {loadFailed
              ? "Your tokens could not be loaded. Reload the page to try again."
              : "No tokens yet. Create one below."}
          </p>
        ) : (
          <ul className="divide-y divide-(--primary)/10">
            {tokens.map((token) => (
              <li
                key={token.id}
                className="py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2"
              >
                <div className="min-w-0 space-y-0.5">
                  <p className="text-sm flex items-center gap-1 break-all">
                    <KeyIcon
                      size={16}
                      className="shrink-0 text-(--muted-foreground)"
                    />
                    {token.name}
                  </p>
                  <p className="text-xs font-mono text-(--muted-foreground) break-all">
                    ilm_{token.prefix}…
                  </p>
                  <p className="text-xs text-(--muted-foreground)">
                    Created {formatDate(token.created_at)} · Last used{" "}
                    {token.last_used_at
                      ? formatDate(token.last_used_at)
                      : "never"}{" "}
                    · Expires{" "}
                    {token.expires_at ? formatDate(token.expires_at) : "never"}
                  </p>
                </div>

                {confirming === token.id ? (
                  <div className="flex flex-wrap items-center gap-2 shrink-0">
                    <span className="text-xs">Revoke this token?</span>
                    <Button
                      type="button"
                      size="xs"
                      loading={revoking === token.id}
                      onClick={() => handleRevoke(token.id)}
                    >
                      Confirm revoke
                    </Button>
                    <Button
                      type="button"
                      size="xs"
                      className="bg-(--muted) text-(--foreground)"
                      onClick={() => setConfirming(null)}
                    >
                      Cancel
                    </Button>
                  </div>
                ) : (
                  <Button
                    type="button"
                    size="xs"
                    className="gap-1 shrink-0 self-start sm:self-auto"
                    aria-label={`Revoke ${token.name}`}
                    onClick={() => {
                      setRevokeError(null);
                      setConfirming(token.id);
                    }}
                  >
                    <TrashIcon size={13} />
                    Revoke
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        {revokeError && <p className="text-xs text-red-400">{revokeError}</p>}

        <form
          onSubmit={handleCreate}
          noValidate
          className="flex flex-col sm:flex-row sm:items-end gap-3"
        >
          <div className="flex flex-col gap-1 flex-1 min-w-0">
            <label htmlFor="mcp-token-name" className="text-sm">
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
          <Button
            type="submit"
            size="md"
            loading={creating}
            className="gap-1.5"
          >
            <PlusIcon size={15} />
            New token
          </Button>
        </form>
        {createError && <p className="text-xs text-red-400">{createError}</p>}
      </div>

      <div className="px-5 py-4 space-y-3">
        <p className="text-sm">Connect a client</p>
        <div role="tablist" className="flex flex-wrap gap-1">
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
              className={`px-3 py-1.5 text-xs rounded-sm border cursor-pointer transition-colors ${
                tab === id
                  ? "border-(--primary)/40 bg-(--muted)/60"
                  : "border-(--border) text-(--muted-foreground)"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="text-xs text-(--muted-foreground)">{TAB_HINTS[tab]}</p>
        <div className="relative">
          <pre
            data-testid="mcp-snippet"
            className="rounded-sm border border-(--border) bg-(--muted)/50 p-3 pr-24 text-xs font-mono overflow-x-auto whitespace-pre"
          >
            {snippet}
          </pre>
          <Button
            type="button"
            size="xs"
            className="absolute top-2 right-2 gap-1"
            onClick={() => copy(snippet, "snippet")}
          >
            {copied === "snippet" ? (
              <CheckIcon size={12} />
            ) : (
              <CopyIcon size={12} />
            )}
            {copied === "snippet" ? "Copied" : "Copy snippet"}
          </Button>
        </div>
        <p className="text-xs text-(--muted-foreground)">
          The AI tool will read text from your repositories, including commit
          messages and PR descriptions written by others, so treat its
          suggestions to run commands with the usual care. A token reads private
          code, so keep its expiry short.
        </p>
      </div>
    </div>
  );
}
