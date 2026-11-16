import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import McpSettings from "@/components/McpSettings";
import type { McpToken } from "@/types/mcp";

// Server actions call `cookies()`, which only works inside a request scope;
// the route is tested on the server, so the actions are stubbed here.
vi.mock("@/actions/mcpTokens", () => ({
  listMcpTokens: vi.fn(),
  createMcpToken: vi.fn(),
  revokeMcpToken: vi.fn(),
}));

import { createMcpToken, revokeMcpToken } from "@/actions/mcpTokens";

const createMock = vi.mocked(createMcpToken);
const revokeMock = vi.mocked(revokeMcpToken);

const PLAINTEXT = "ilm_abcd1234_secretsecretsecret";

function makeToken(overrides: Partial<McpToken> = {}): McpToken {
  return {
    id: "t1",
    name: "Laptop",
    prefix: "abcd1234",
    created_at: "2026-01-05T10:00:00Z",
    last_used_at: null,
    expires_at: "2026-04-05T10:00:00Z",
    ...overrides,
  };
}

function snippet() {
  return screen.getByTestId("mcp-snippet").textContent ?? "";
}

beforeEach(() => {
  createMock.mockReset();
  revokeMock.mockReset();
  revokeMock.mockResolvedValue(undefined);
});

async function createToken(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/token name/i), "CI box");
  await user.click(screen.getByRole("button", { name: /new token/i }));
}

describe("McpSettings", () => {
  it("lists tokens with prefix, last used and expiry", () => {
    render(
      <McpSettings
        initialTokens={[
          makeToken(),
          makeToken({
            id: "t2",
            name: "Desktop",
            prefix: "zzzz9999",
            last_used_at: "2026-02-01T10:00:00Z",
            expires_at: null,
          }),
        ]}
      />,
    );

    expect(screen.getByText("Laptop")).toBeInTheDocument();
    expect(screen.getByText("ilm_abcd1234…")).toBeInTheDocument();
    expect(screen.getByText("ilm_zzzz9999…")).toBeInTheDocument();
    expect(screen.getByText(/last used never/i)).toBeInTheDocument();
    expect(screen.getByText(/expires never/i)).toBeInTheDocument();
  });

  it("shows an empty state", () => {
    render(<McpSettings initialTokens={[]} />);
    expect(screen.getByText(/no tokens yet/i)).toBeInTheDocument();
  });

  it("says the list failed to load instead of claiming there are no tokens", () => {
    render(<McpSettings initialTokens={[]} loadFailed />);
    expect(screen.getByText(/could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(/no tokens yet/i)).not.toBeInTheDocument();
  });

  it("shows the plaintext once and drops it when dismissed", async () => {
    createMock.mockResolvedValueOnce({
      ...makeToken({ id: "t9", name: "CI box" }),
      token: PLAINTEXT,
    });
    const user = userEvent.setup();
    render(<McpSettings initialTokens={[]} />);

    await createToken(user);

    expect(createMock).toHaveBeenCalledWith({
      name: "CI box",
      expiresInDays: 90,
    });
    const field = (await screen.findByLabelText(
      "New token",
    )) as HTMLInputElement;
    expect(field.value).toBe(PLAINTEXT);
    expect(field).toHaveAttribute("readonly");
    expect(screen.getByText(/you won.t see this again/i)).toBeInTheDocument();
    expect(screen.getByText("CI box")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^done$/i }));

    expect(screen.queryByLabelText("New token")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(PLAINTEXT);
  });

  it("fills the snippets with the backend URL, and the token only while visible", async () => {
    createMock.mockResolvedValueOnce({ ...makeToken(), token: PLAINTEXT });
    const user = userEvent.setup();
    render(<McpSettings initialTokens={[]} />);
    const backend = process.env.NEXT_PUBLIC_BACKEND_URL;

    expect(snippet()).toContain(`${backend}/mcp`);
    expect(snippet()).toContain("<your token>");

    await createToken(user);
    await screen.findByLabelText("New token");

    for (const tab of ["Claude Code", "Cursor", "VS Code", "Local launcher"]) {
      await user.click(screen.getByRole("tab", { name: tab }));
      expect(snippet()).toContain(PLAINTEXT);
      expect(snippet()).not.toContain("<your token>");
      if (tab !== "Local launcher") {
        expect(snippet()).toContain(`${backend}/mcp`);
      }
    }

    // The launcher keeps the token in the environment, not on the command line.
    expect(snippet()).toContain("ILLUME_MCP_TOKEN");
    expect(snippet()).toContain("illume-mcp");

    await user.click(screen.getByRole("button", { name: /^done$/i }));

    expect(snippet()).not.toContain(PLAINTEXT);
    expect(snippet()).toContain("<your token>");
    await user.click(screen.getByRole("tab", { name: "Claude Code" }));
    expect(snippet()).toMatch(
      /^claude mcp add --transport http illume .*\/mcp --header "Authorization: Bearer <your token>"$/,
    );
  });

  it("revokes only after a confirm and removes the row", async () => {
    const user = userEvent.setup();
    render(
      <McpSettings
        initialTokens={[makeToken(), makeToken({ id: "t2", name: "Desktop" })]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Revoke Laptop" }));
    expect(revokeMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /confirm revoke/i }));

    await waitFor(() => expect(revokeMock).toHaveBeenCalledWith("t1"));
    await waitFor(() =>
      expect(screen.queryByText("Laptop")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Desktop")).toBeInTheDocument();
  });

  it("keeps the row when the confirm is cancelled", async () => {
    const user = userEvent.setup();
    render(<McpSettings initialTokens={[makeToken()]} />);

    await user.click(screen.getByRole("button", { name: "Revoke Laptop" }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(revokeMock).not.toHaveBeenCalled();
    expect(screen.getByText("Laptop")).toBeInTheDocument();
  });

  it("shows the server's message when creation fails", async () => {
    createMock.mockRejectedValueOnce(
      new Error("You already have 10 active tokens. Revoke one first."),
    );
    const user = userEvent.setup();
    render(<McpSettings initialTokens={[]} />);

    await createToken(user);

    expect(
      await screen.findByText(/already have 10 active tokens/i),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("New token")).not.toBeInTheDocument();
  });

  it("asks for a name without calling the server", async () => {
    const user = userEvent.setup();
    render(<McpSettings initialTokens={[]} />);

    await user.click(screen.getByRole("button", { name: /new token/i }));

    expect(screen.getByText(/give the token a name/i)).toBeInTheDocument();
    expect(createMock).not.toHaveBeenCalled();
  });

  it("sends a null lifetime when never is chosen", async () => {
    createMock.mockResolvedValueOnce({ ...makeToken(), token: PLAINTEXT });
    const user = userEvent.setup();
    render(<McpSettings initialTokens={[]} />);

    await user.click(screen.getByRole("combobox", { name: /expires/i }));
    await user.click(screen.getByRole("option", { name: "Never" }));
    await createToken(user);

    await waitFor(() =>
      expect(createMock).toHaveBeenCalledWith({
        name: "CI box",
        expiresInDays: null,
      }),
    );
  });

  it("names the placement of each snippet", async () => {
    const user = userEvent.setup();
    render(<McpSettings initialTokens={[]} />);

    await user.click(screen.getByRole("tab", { name: "VS Code" }));
    expect(screen.getByText(/\.vscode\/mcp\.json/)).toBeInTheDocument();
    expect(
      within(screen.getByRole("tablist")).getAllByRole("tab"),
    ).toHaveLength(4);
  });
});
