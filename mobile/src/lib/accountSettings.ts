/**
 * Pure rules for the account settings forms.
 *
 * @module accountSettings
 *
 * Mirrors the web client's `agentSettingsSchema` and the checks inside its
 * MCP and delete-account cards.
 */

/** The bounds of the agent context window; mirror the server's constants. */
export const MIN_CONTEXT_WINDOW = 32_000;
export const MAX_CONTEXT_WINDOW = 1_000_000;

/** Common context windows offered as one-tap choices. */
export const CONTEXT_PRESETS = [
  { label: "128K", tokens: 128_000 },
  { label: "200K", tokens: 200_000 },
  { label: "400K", tokens: 400_000 },
  { label: "1M", tokens: 1_000_000 },
] as const;

/** The outcome of reading the context-window field. */
export type ContextWindowParse =
  | { ok: true; value: number | null }
  | { ok: false; message: string };

/**
 * Read the context-window field.
 *
 * Separators and spaces are ignored; blank means "use the default".
 *
 * @param raw - What was typed.
 * @param min - Lowest accepted value.
 * @param max - Highest accepted value.
 * @returns The value to save, or the message to show.
 */
export function parseContextWindow(
  raw: string,
  min = MIN_CONTEXT_WINDOW,
  max = MAX_CONTEXT_WINDOW,
): ContextWindowParse {
  const cleaned = raw.trim().replace(/[,_\s]/g, "");
  if (cleaned === "") return { ok: true, value: null };
  const value = Number(cleaned);
  if (!/^\d+$/.test(cleaned) || value < min || value > max) {
    return {
      ok: false,
      message: `Enter a whole number from ${min.toLocaleString("en-US")} to ${max.toLocaleString("en-US")}, or leave it blank for the default.`,
    };
  }
  return { ok: true, value };
}

/**
 * Whether the typed email matches the account's, ignoring case and spaces.
 *
 * @param typed - What was typed.
 * @param email - The account email.
 * @returns True when deletion may proceed.
 */
export function emailConfirms(typed: string, email: string): boolean {
  return (
    email.trim().length > 0 &&
    typed.trim().toLowerCase() === email.trim().toLowerCase()
  );
}

/** The lifetimes the token form offers; `null` is never. */
export const TOKEN_EXPIRIES: { label: string; days: 30 | 90 | null }[] = [
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
  { label: "Never", days: null },
];

/** The clients the setup snippets cover. */
export type SnippetTab = "claude-code" | "cursor" | "vscode" | "codex";

/** Shown in the snippets whenever no fresh token is on screen. */
export const TOKEN_PLACEHOLDER = "<your token>";

/**
 * The setup snippet that connects an AI client to the MCP server.
 *
 * @param tab - The client.
 * @param url - The MCP endpoint.
 * @param token - A fresh plaintext token, or the placeholder.
 * @returns The text to paste.
 */
export function buildSnippet(tab: SnippetTab, url: string, token: string): string {
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
        { servers: { illume: { type: "http", url, headers: { Authorization: header } } } },
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
  }
}
