import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import AgentSettingsScreen from "@/app/(app)/settings/agent";
import DeleteAccountScreen from "@/app/(app)/settings/delete-account";
import McpSettingsScreen from "@/app/(app)/settings/mcp";
import * as account from "@/api/account";
import {
  buildSnippet,
  emailConfirms,
  parseContextWindow,
} from "@/lib/accountSettings";

jest.mock("expo-router", () => ({
  router: { back: jest.fn(), push: jest.fn(), replace: jest.fn() },
}));

const mockSignOut = jest.fn(async () => {});
const mockRefresh = jest.fn(async () => {});
jest.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    user: { id: "u", email: "Ada@Example.com", mcp_enabled: true },
    signOut: mockSignOut,
    refreshUser: mockRefresh,
  }),
}));

jest.mock("@/api/account", () => ({
  getAgentSettings: jest.fn(),
  saveAgentSettings: jest.fn(),
  listMcpTokens: jest.fn(),
  createMcpToken: jest.fn(),
  revokeMcpToken: jest.fn(),
  deleteAccount: jest.fn(),
}));
const api = account as jest.Mocked<typeof account>;

function wrap(node: React.ReactElement) {
  return (
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 360, height: 800 },
        insets: { top: 0, left: 0, right: 0, bottom: 0 },
      }}
    >
      {node}
    </SafeAreaProvider>
  );
}

describe("parseContextWindow", () => {
  it("treats blank as the default and ignores separators", () => {
    expect(parseContextWindow("  ")).toEqual({ ok: true, value: null });
    expect(parseContextWindow("200,000")).toEqual({ ok: true, value: 200000 });
    expect(parseContextWindow("1_000_000")).toEqual({ ok: true, value: 1000000 });
  });

  it("rejects values outside the bounds or not whole numbers", () => {
    expect(parseContextWindow("100").ok).toBe(false);
    expect(parseContextWindow("2000000").ok).toBe(false);
    expect(parseContextWindow("12.5k").ok).toBe(false);
    expect(parseContextWindow("-5").ok).toBe(false);
  });
});

describe("account helpers", () => {
  it("confirms an email ignoring case and spaces", () => {
    expect(emailConfirms(" ada@example.COM ", "Ada@Example.com")).toBe(true);
    expect(emailConfirms("other@example.com", "ada@example.com")).toBe(false);
    expect(emailConfirms("", "")).toBe(false);
  });

  it("builds a snippet per client", () => {
    expect(buildSnippet("claude-code", "https://h/mcp", "ilm_x")).toContain(
      'Authorization: Bearer ilm_x',
    );
    expect(JSON.parse(buildSnippet("cursor", "https://h/mcp", "t")).mcpServers.illume.url).toBe(
      "https://h/mcp",
    );
    expect(buildSnippet("codex", "https://h/mcp", "t")).toContain("bearer_token_env_var");
  });
});

describe("AgentSettingsScreen", () => {
  beforeEach(() => jest.clearAllMocks());

  it("saves a valid window and refreshes the profile", async () => {
    api.getAgentSettings.mockResolvedValue({
      context_window: null,
      context_window_default: 250000,
      context_window_min: 32000,
      context_window_max: 1000000,
    });
    api.saveAgentSettings.mockResolvedValue({
      context_window: 200000,
      context_window_default: 250000,
      context_window_min: 32000,
      context_window_max: 1000000,
    });
    await act(async () => {
      await render(wrap(<AgentSettingsScreen />));
    });
    await fireEvent.press(screen.getByTestId("context-preset-200K"));
    await act(async () => {
      await fireEvent.press(screen.getByTestId("agent-settings-save"));
    });
    expect(api.saveAgentSettings).toHaveBeenCalledWith(200000);
    await waitFor(() => expect(screen.getByTestId("agent-settings-saved")).toBeTruthy());
    expect(mockRefresh).toHaveBeenCalled();
  });

  it("refuses an out-of-range value without calling the server", async () => {
    api.getAgentSettings.mockResolvedValue({
      context_window: null,
      context_window_default: 250000,
      context_window_min: 32000,
      context_window_max: 1000000,
    });
    await act(async () => {
      await render(wrap(<AgentSettingsScreen />));
    });
    await fireEvent.changeText(screen.getByTestId("context-window-input"), "5");
    await act(async () => {
      await fireEvent.press(screen.getByTestId("agent-settings-save"));
    });
    expect(screen.getByTestId("agent-settings-error")).toBeTruthy();
    expect(api.saveAgentSettings).not.toHaveBeenCalled();
  });
});

describe("McpSettingsScreen", () => {
  beforeEach(() => jest.clearAllMocks());

  it("lists tokens, creates one and shows its plaintext once", async () => {
    api.listMcpTokens.mockResolvedValue([
      {
        id: "t1",
        name: "Laptop",
        prefix: "abcd",
        created_at: "2026-01-01T00:00:00Z",
        last_used_at: null,
        expires_at: null,
      },
    ]);
    api.createMcpToken.mockResolvedValue({
      id: "t2",
      name: "Desktop",
      prefix: "wxyz",
      created_at: "2026-01-02T00:00:00Z",
      last_used_at: null,
      expires_at: null,
      token: "ilm_secret",
    });
    await act(async () => {
      await render(wrap(<McpSettingsScreen />));
    });
    expect(screen.getByTestId("mcp-token-t1")).toBeTruthy();

    await act(async () => {
      await fireEvent.press(screen.getByTestId("mcp-create"));
    });
    expect(screen.getByTestId("mcp-error")).toBeTruthy();

    await fireEvent.changeText(screen.getByTestId("mcp-token-name"), "Desktop");
    await act(async () => {
      await fireEvent.press(screen.getByTestId("mcp-create"));
    });
    expect(api.createMcpToken).toHaveBeenCalledWith({ name: "Desktop", expiresInDays: 90 });
    expect(screen.getByText("ilm_secret")).toBeTruthy();
    expect(screen.getByTestId("mcp-token-t2")).toBeTruthy();
    // The snippet now carries the fresh token.
    expect(screen.getByTestId("mcp-snippet").props.children).toContain("ilm_secret");
  });

  it("shows the placeholder in snippets when no token is fresh", async () => {
    api.listMcpTokens.mockResolvedValue([]);
    await act(async () => {
      await render(wrap(<McpSettingsScreen />));
    });
    expect(screen.getByTestId("mcp-snippet").props.children).toContain("<your token>");
    await fireEvent.press(screen.getByTestId("mcp-tab-cursor"));
    expect(screen.getByTestId("mcp-snippet").props.children).toContain("mcpServers");
  });
});

describe("DeleteAccountScreen", () => {
  beforeEach(() => jest.clearAllMocks());

  it("stays disabled until the email matches, then deletes and signs out", async () => {
    api.deleteAccount.mockResolvedValue(undefined);
    await act(async () => {
      await render(wrap(<DeleteAccountScreen />));
    });
    const confirm = () => screen.getByTestId("delete-account-confirm");
    expect(confirm().props.accessibilityState.disabled).toBe(true);
    await fireEvent.changeText(screen.getByTestId("delete-account-email"), "wrong@example.com");
    expect(confirm().props.accessibilityState.disabled).toBe(true);
    await fireEvent.changeText(screen.getByTestId("delete-account-email"), "ada@example.com");
    expect(confirm().props.accessibilityState.disabled).toBe(false);
    await act(async () => {
      await fireEvent.press(confirm());
    });
    expect(api.deleteAccount).toHaveBeenCalledWith("ada@example.com");
    expect(mockSignOut).toHaveBeenCalled();
  });

  it("shows the failure and stays signed in", async () => {
    api.deleteAccount.mockRejectedValue(new Error("Nope"));
    await act(async () => {
      await render(wrap(<DeleteAccountScreen />));
    });
    await fireEvent.changeText(screen.getByTestId("delete-account-email"), "ada@example.com");
    await act(async () => {
      await fireEvent.press(screen.getByTestId("delete-account-confirm"));
    });
    expect(screen.getByTestId("delete-account-error")).toBeTruthy();
    expect(mockSignOut).not.toHaveBeenCalled();
  });
});
