import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentSettings from "@/components/AgentSettings";
import User from "@/types/user";

const refresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh,
    back: vi.fn(),
  }),
}));

// Server actions call `cookies()`, which only works inside a request scope;
// the route is tested on the server, so the action is stubbed here.
vi.mock("@/actions/saveAgentSettings", () => ({
  default: vi.fn(),
}));

import saveAgentSettingsAction from "@/actions/saveAgentSettings";

const saveMock = vi.mocked(saveAgentSettingsAction);

function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: "u1",
    name: "Tester",
    email: "tester@example.com",
    avatar_url: null,
    github_id: null,
    ai_provider: null,
    ai_model: null,
    has_ai_key: false,
    free_ingestions_used: 0,
    free_chat_messages_used: 0,
    free_ingestions_limit: 3,
    free_chat_messages_limit: 5,
    ...overrides,
  };
}

function field() {
  return screen.getByLabelText(/context window/i) as HTMLInputElement;
}

beforeEach(() => {
  refresh.mockReset();
  saveMock.mockReset();
  saveMock.mockResolvedValue(undefined as never);
});

describe("AgentSettings", () => {
  it("shows the server default as the placeholder when nothing is saved", () => {
    render(
      <AgentSettings user={makeUser({ ai_context_window_default: 250_000 })} />,
    );
    expect(field().value).toBe("");
    expect(field().placeholder).toBe("250,000");
  });

  it("seeds the field with the saved window", () => {
    render(<AgentSettings user={makeUser({ ai_context_window: 500_000 })} />);
    expect(field().value).toBe("500000");
  });

  it("saves a window without asking for the API key", async () => {
    const user = userEvent.setup();
    render(<AgentSettings user={makeUser({ has_ai_key: true })} />);

    await user.type(field(), "400,000");
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(saveMock).toHaveBeenCalledWith({ contextWindow: 400_000 }),
    );
    expect(refresh).toHaveBeenCalled();
    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();
  });

  it("saves a blank field as a reset to the default", async () => {
    const user = userEvent.setup();
    render(<AgentSettings user={makeUser({ ai_context_window: 500_000 })} />);

    await user.clear(field());
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(saveMock).toHaveBeenCalledWith({ contextWindow: null }),
    );
  });

  it.each(["31999", "1000001", "abc", "1.5"])(
    "refuses %s without calling the server",
    async (input) => {
      const user = userEvent.setup();
      render(<AgentSettings user={makeUser()} />);

      await user.type(field(), input);
      await user.click(screen.getByRole("button", { name: /save/i }));

      expect(
        await screen.findByText(/whole number from 32,000 to 1,000,000/i),
      ).toBeInTheDocument();
      expect(saveMock).not.toHaveBeenCalled();
    },
  );

  it("shows the server's message when the save fails", async () => {
    saveMock.mockRejectedValueOnce(new Error("Not authenticated"));
    const user = userEvent.setup();
    render(<AgentSettings user={makeUser()} />);

    await user.type(field(), "64000");
    await user.click(screen.getByRole("button", { name: /save/i }));

    expect(await screen.findByText("Not authenticated")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });
});
