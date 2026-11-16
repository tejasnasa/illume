/**
 * Server actions listing, creating and revoking the current user's MCP tokens.
 * @module McpTokensActions
 */

"use server";

import type {
  CreateMcpTokenPayload,
  CreatedMcpToken,
  McpToken,
} from "@/types/mcp";
import { cookies } from "next/headers";

const TOKENS_PATH = "/api/v1/auth/me/mcp-tokens";

/**
 * Reads the backend's `detail` from a failed response, falling back to a
 * generic message when the body is not JSON or carries a validation list.
 *
 * @param res - The failed response.
 * @param fallback - Message used when no string detail is present.
 * @returns The message to surface.
 */
async function failureDetail(res: Response, fallback: string) {
  try {
    const err = await res.json();
    return typeof err.detail === "string" ? err.detail : fallback;
  } catch {
    return fallback;
  }
}

/**
 * Lists the user's active MCP tokens, newest first.
 *
 * @returns The active tokens.
 * @throws Error when the backend rejects the request.
 */
export async function listMcpTokens(): Promise<McpToken[]> {
  const cookieStore = await cookies();

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}${TOKENS_PATH}`,
    {
      headers: { Cookie: cookieStore.toString() },
      cache: "no-store",
    },
  );

  if (!res.ok) {
    throw new Error(await failureDetail(res, "Failed to load tokens"));
  }
  return res.json();
}

/**
 * Creates a token. The response carries the plaintext, which the backend
 * never returns again.
 *
 * @param payload - Name and lifetime for the new token.
 * @returns The created token including its plaintext.
 * @throws Error with the backend message, e.g. when the token cap is reached.
 */
export async function createMcpToken(
  payload: CreateMcpTokenPayload,
): Promise<CreatedMcpToken> {
  const cookieStore = await cookies();

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}${TOKENS_PATH}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Cookie: cookieStore.toString(),
      },
      body: JSON.stringify({
        name: payload.name,
        expires_in_days: payload.expiresInDays,
      }),
      cache: "no-store",
    },
  );

  if (!res.ok) {
    throw new Error(await failureDetail(res, "Failed to create token"));
  }
  return res.json();
}

/**
 * Revokes a token. The backend treats a repeat as a success.
 *
 * @param tokenId - Id of the token to revoke.
 * @throws Error when the token is unknown or the request fails.
 */
export async function revokeMcpToken(tokenId: string): Promise<void> {
  const cookieStore = await cookies();

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}${TOKENS_PATH}/${encodeURIComponent(tokenId)}`,
    {
      method: "DELETE",
      headers: { Cookie: cookieStore.toString() },
      cache: "no-store",
    },
  );

  if (!res.ok) {
    throw new Error(await failureDetail(res, "Failed to revoke token"));
  }
}
