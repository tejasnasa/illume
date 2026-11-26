import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Settings from "@/app/settings/page";
import type User from "@/types/user";

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: () => ({ value: "token" }),
    toString: () => "",
  }),
  headers: async () => new Headers(),
}));

vi.mock("@/components/Navbar", () => ({ default: () => null }));
vi.mock("@/components/AiSettings", () => ({ default: () => null }));
vi.mock("@/components/AgentSettings", () => ({ default: () => null }));
vi.mock("@/components/McpSettings", () => ({
  default: () => <div data-testid="mcp-card" />,
}));

const api = vi.hoisted(() => ({ user: vi.fn(), tokens: vi.fn(), repos: vi.fn() }));

vi.mock("@/api/auth", () => ({ default: api.user }));
vi.mock("@/actions/mcpTokens", () => ({ listMcpTokens: api.tokens }));
vi.mock("@/api/repository", () => ({ getRepositories: api.repos }));

function makeUser(mcpEnabled: boolean): User {
  return {
    id: "u1",
    name: "Ada",
    email: "ada@example.com",
    avatar_url: null,
    github_id: null,
    ai_provider: null,
    ai_model: null,
    has_ai_key: false,
    free_ingestions_used: 0,
    free_chat_messages_used: 0,
    free_ingestions_limit: 3,
    free_chat_messages_limit: 5,
    mcp_enabled: mcpEnabled,
  };
}

beforeEach(() => {
  api.user.mockReset();
  api.tokens.mockReset();
  api.tokens.mockResolvedValue([]);
  api.repos.mockReset();
  api.repos.mockResolvedValue([]);
});

describe("settings page MCP card", () => {
  it("shows the MCP card when the server has MCP on", async () => {
    api.user.mockResolvedValue(makeUser(true));

    render(await Settings());

    expect(screen.getByTestId("mcp-card")).toBeInTheDocument();
    expect(api.tokens).toHaveBeenCalledTimes(1);
  });

  it("hides the MCP card, and skips listing tokens, when the server has MCP off", async () => {
    api.user.mockResolvedValue(makeUser(false));

    render(await Settings());

    expect(screen.queryByTestId("mcp-card")).not.toBeInTheDocument();
    expect(api.tokens).not.toHaveBeenCalled();
  });
});

describe("settings page account and danger zone", () => {
  it("says when the account was created", async () => {
    api.user.mockResolvedValue({ ...makeUser(false), created_at: "2026-03-14T09:00:00Z" });

    render(await Settings());

    expect(screen.getByText("Member since Mar 2026")).toBeInTheDocument();
  });

  it("counts what deleting the account would remove", async () => {
    api.user.mockResolvedValue(makeUser(true));
    api.repos.mockResolvedValue([{ id: "r1" }, { id: "r2" }]);
    api.tokens.mockResolvedValue([{ id: "t1" }]);

    render(await Settings());

    expect(screen.getByRole("button", { name: "Delete account" })).toBeInTheDocument();
    expect(screen.getByText("2 repositories · 1 token")).toBeInTheDocument();
  });

  it("still offers deletion when the repositories cannot be counted", async () => {
    api.user.mockResolvedValue(makeUser(false));
    api.repos.mockRejectedValue(new Error("down"));

    render(await Settings());

    expect(screen.getByRole("button", { name: "Delete account" })).toBeInTheDocument();
  });
});
