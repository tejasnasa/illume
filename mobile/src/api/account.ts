/**
 * Account endpoints: agent settings, MCP access tokens and account deletion.
 *
 * @module AccountApi
 *
 * - ``GET/PUT /api/v1/auth/me/agent-settings``  the agent context window
 * - ``GET/POST /api/v1/auth/me/mcp-tokens``     list and create tokens
 * - ``DELETE /api/v1/auth/me/mcp-tokens/{id}``  revoke one
 * - ``DELETE /api/v1/auth/me``                  delete the account
 */

import {
  apiDelete,
  apiGet,
  apiPost,
  apiPut,
  apiRequest,
  type ApiRequestOptions,
} from "@/api/client";
import type {
  CreateMcpTokenPayload,
  CreatedMcpToken,
  McpToken,
} from "@/types/mcp";

type TestOptions = Omit<ApiRequestOptions, "method" | "body">;

/** The agent settings with the bounds the form validates against. */
export interface AgentSettings {
  context_window: number | null;
  context_window_default: number;
  context_window_min: number;
  context_window_max: number;
}

const TOKENS_PATH = "/api/v1/auth/me/mcp-tokens";

/** Read the agent settings. */
export function getAgentSettings(options: TestOptions = {}): Promise<AgentSettings> {
  return apiGet("/api/v1/auth/me/agent-settings", options);
}

/**
 * Save the agent context window.
 *
 * @param contextWindow - Tokens one model call may carry; null resets to the default.
 * @param options - Test seams.
 */
export function saveAgentSettings(
  contextWindow: number | null,
  options: TestOptions = {},
): Promise<AgentSettings> {
  return apiPut(
    "/api/v1/auth/me/agent-settings",
    { context_window: contextWindow },
    options,
  );
}

/** List the user's active MCP tokens. */
export function listMcpTokens(options: TestOptions = {}): Promise<McpToken[]> {
  return apiGet(TOKENS_PATH, options);
}

/** Create an MCP token; the plaintext is returned exactly once. */
export function createMcpToken(
  payload: CreateMcpTokenPayload,
  options: TestOptions = {},
): Promise<CreatedMcpToken> {
  return apiPost(
    TOKENS_PATH,
    { name: payload.name, expires_in_days: payload.expiresInDays },
    options,
  );
}

/** Revoke an MCP token. */
export function revokeMcpToken(
  tokenId: string,
  options: TestOptions = {},
): Promise<unknown> {
  return apiDelete(`${TOKENS_PATH}/${encodeURIComponent(tokenId)}`, options);
}

/**
 * Delete the signed-in account and everything it owns.
 *
 * @param confirmEmail - The account email typed as confirmation.
 * @param options - Test seams.
 */
export async function deleteAccount(
  confirmEmail: string,
  options: TestOptions = {},
): Promise<void> {
  await apiRequest("/api/v1/auth/me", {
    ...options,
    method: "DELETE",
    body: { confirm_email: confirmEmail },
  });
}
