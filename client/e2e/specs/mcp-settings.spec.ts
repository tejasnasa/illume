import { expect, test, type APIRequestContext } from "@playwright/test";

import { API_URL } from "../env";

/**
 * MCP token lifecycle, from the Settings page to a live MCP call.
 *
 * A token is created in the UI, used against the real `/mcp` endpoint, then
 * revoked in the UI and shown to be refused. The server is stateless, so each
 * POST stands alone and the reply is a single SSE event.
 */

const MCP_HEADERS = {
  "Content-Type": "application/json",
  Accept: "application/json, text/event-stream",
  "MCP-Protocol-Version": "2025-11-25",
};

/** Parses the JSON-RPC message out of an SSE (or plain JSON) reply body. */
function parseRpc(body: string): { result?: { tools?: { name: string }[] } } {
  const data = body
    .split("\n")
    .find((line) => line.startsWith("data:"))
    ?.slice("data:".length)
    .trim();
  return JSON.parse(data ?? body);
}

/** Sends one JSON-RPC request to the MCP endpoint with the given token. */
function rpc(
  request: APIRequestContext,
  token: string,
  payload: Record<string, unknown>,
) {
  return request.post(`${API_URL}/mcp`, {
    headers: { ...MCP_HEADERS, Authorization: `Bearer ${token}` },
    data: { jsonrpc: "2.0", ...payload },
  });
}

test("a token made in Settings works against /mcp until it is revoked", async ({
  page,
  playwright,
}) => {
  const name = `e2e-mcp-${Date.now()}`;
  const anonymous = await playwright.request.newContext();
  let revoked = false;

  try {
    await page.goto("/settings");
    await page.getByLabel(/token name/i).fill(name);
    await page.getByRole("button", { name: /new token/i }).click();

    const field = page.getByLabel("New token");
    await expect(field).toBeVisible();
    const token = await field.inputValue();
    expect(token).toMatch(/^ilm_/);
    await expect(page.getByText(/you won.t see this again/i)).toBeVisible();

    const init = await rpc(anonymous, token, {
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2025-11-25",
        capabilities: {},
        clientInfo: { name: "e2e", version: "0" },
      },
    });
    expect(init.status()).toBe(200);

    const list = await rpc(anonymous, token, {
      id: 2,
      method: "tools/list",
      params: {},
    });
    expect(list.status()).toBe(200);
    const tools = parseRpc(await list.text()).result?.tools ?? [];
    expect(tools.map((tool) => tool.name)).toContain("list_repositories");

    await page.getByRole("button", { name: /^done$/i }).click();
    await expect(page.getByLabel("New token")).toHaveCount(0);

    await page.getByRole("button", { name: `Revoke ${name}` }).click();
    await page.getByRole("button", { name: /confirm revoke/i }).click();
    await expect(page.getByText(name)).toHaveCount(0);
    revoked = true;

    const after = await rpc(anonymous, token, {
      id: 3,
      method: "tools/list",
      params: {},
    });
    expect(after.status()).toBe(401);
  } finally {
    // A failure part-way must not leave a live token behind.
    if (!revoked) {
      await page.goto("/settings");
      const revoke = page.getByRole("button", { name: `Revoke ${name}` });
      if (await revoke.count()) {
        await revoke.click();
        await page.getByRole("button", { name: /confirm revoke/i }).click();
      }
    }
    await anonymous.dispose();
  }
});
