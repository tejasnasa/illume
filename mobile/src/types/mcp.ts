/**
 * MCP access token response and request shapes.
 * @module McpTypes
 */

/**
 * One active MCP token as listed by the API. The hash and the plaintext are
 * never part of it.
 */
export interface McpToken {
  id: string;
  name: string;
  /** The first characters of the token, shown after the `ilm_` marker. */
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  /** `null` for a token that never expires. */
  expires_at: string | null;
}

/**
 * The creation response: the listed fields plus the plaintext, which the API
 * returns exactly once.
 */
export interface CreatedMcpToken extends McpToken {
  token: string;
}

/** Lifetimes the create form offers; `null` is never. */
export type McpTokenExpiry = 30 | 90 | null;

/** Payload for creating a token. */
export interface CreateMcpTokenPayload {
  name: string;
  expiresInDays: McpTokenExpiry;
}
