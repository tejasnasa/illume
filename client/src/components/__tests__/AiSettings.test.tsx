import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AiSettings from "@/components/AiSettings";
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

// Server actions call `cookies()` which is only valid inside a Next.js request
// scope. The actions themselves are tested at the route level; here we stub
// them so the component runs end-to-end.
vi.mock("@/actions/saveAiCredentials", () => ({
  default: vi.fn(),
}));
vi.mock("@/actions/removeAiCredentials", () => ({
  default: vi.fn(),
}));

import removeAiCredentialsAction from "@/actions/removeAiCredentials";
import saveAiCredentialsAction from "@/actions/saveAiCredentials";

const saveAiCredentialsMock = vi.mocked(saveAiCredentialsAction);
const removeAiCredentialsMock = vi.mocked(removeAiCredentialsAction);

/**
 * Builds a user with sensible defaults; tests override the bits they care about.
 */
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

beforeEach(() => {
  refresh.mockReset();
  saveAiCredentialsMock.mockReset();
  removeAiCredentialsMock.mockReset();
  saveAiCredentialsMock.mockResolvedValue(undefined as never);
  removeAiCredentialsMock.mockResolvedValue(undefined as never);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("layout", () => {
  it("renders the AI Provider section heading", () => {
    render(<AiSettings user={makeUser()} />);

    expect(screen.getByText(/AI Provider/i)).toBeInTheDocument();
  });

  it("renders the provider trigger as a full-width block-level element", () => {
    render(<AiSettings user={makeUser()} />);

    // The wrapper around the dropdown trigger must be `block` (not
    // `inline-block`) so the trigger fills its parent column.
    const trigger = screen.getByRole("button", { name: /OpenAI/i });
    const wrapper = trigger.parentElement;
    expect(wrapper).not.toBeNull();
    expect(wrapper!.className).toContain("block");
    expect(wrapper!.className).not.toContain("inline-block");
    expect(wrapper!.className).toContain("w-full");
    // The button itself must also be full-width -- otherwise it collapses to
    // its content (the inline-flex trigger span) and the picker still looks
    // small even when the wrapper is correct.
    expect(trigger.className).toContain("w-full");
  });

  it("shows the unconnected state when has_ai_key is false", () => {
    render(<AiSettings user={makeUser({ has_ai_key: false })} />);

    expect(screen.queryByText(/Connected/i)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Save key/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Remove key/i }),
    ).not.toBeInTheDocument();
  });

  it("shows the connected state when has_ai_key is true", () => {
    render(
      <AiSettings
        user={makeUser({
          has_ai_key: true,
          ai_provider: "openai",
          ai_model: "gpt-5.6",
        })}
      />,
    );

    expect(screen.getByText(/Connected/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Replace key/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Remove key/i }),
    ).toBeInTheDocument();
  });

  it("seeds the provider picker from ai_provider", () => {
    render(
      <AiSettings
        user={makeUser({ ai_provider: "groq", ai_model: "llama-3.3-70b" })}
      />,
    );

    expect(screen.getByRole("button", { name: /Groq/i })).toBeInTheDocument();
  });

  it("seeds the model input from ai_model", () => {
    render(
      <AiSettings
        user={makeUser({
          ai_provider: "openai",
          ai_model: "gpt-5.6-custom",
        })}
      />,
    );

    expect(screen.getByLabelText(/Model/i)).toHaveValue("gpt-5.6-custom");
  });
});

describe("provider picker", () => {
  it("updates the model placeholder when switching providers", async () => {
    const user = userEvent.setup();
    render(<AiSettings user={makeUser()} />);

    // Initial preset is OpenAI -> gpt-5.6.
    expect(screen.getByLabelText(/Model/i)).toHaveAttribute(
      "placeholder",
      "gpt-5.6",
    );

    // Switch to Groq via the picker.
    await user.click(screen.getByRole("button", { name: /OpenAI/i }));
    await user.click(screen.getByRole("button", { name: /^Groq$/i }));

    expect(screen.getByLabelText(/Model/i)).toHaveAttribute(
      "placeholder",
      "llama-3.3-70b",
    );

    // Switch to DeepSeek.
    await user.click(screen.getByRole("button", { name: /Groq/i }));
    await user.click(screen.getByRole("button", { name: /^DeepSeek$/i }));

    expect(screen.getByLabelText(/Model/i)).toHaveAttribute(
      "placeholder",
      "deepseek-flash",
    );
  });
});

describe("save", () => {
  it("sends the active provider, key, and model on save", async () => {
    const user = userEvent.setup();
    render(<AiSettings user={makeUser()} />);

    await user.type(screen.getByLabelText(/API key/i), "sk-test-key-123");
    await user.click(screen.getByRole("button", { name: /Save key/i }));

    await waitFor(() => expect(saveAiCredentialsMock).toHaveBeenCalledTimes(1));
    expect(saveAiCredentialsMock).toHaveBeenCalledWith({
      provider: "openai",
      apiKey: "sk-test-key-123",
      model: "gpt-5.6",
    });
  });

  it("uses the typed model when one is supplied", async () => {
    const user = userEvent.setup();
    render(<AiSettings user={makeUser()} />);

    await user.type(screen.getByLabelText(/Model/i), "gpt-5.6");
    await user.type(screen.getByLabelText(/API key/i), "sk-test-key");
    await user.click(screen.getByRole("button", { name: /Save key/i }));

    await waitFor(() => expect(saveAiCredentialsMock).toHaveBeenCalledTimes(1));
    expect(saveAiCredentialsMock).toHaveBeenCalledWith({
      provider: "openai",
      apiKey: "sk-test-key",
      model: "gpt-5.6",
    });
  });

  it("refreshes the page on a successful save", async () => {
    const user = userEvent.setup();
    render(<AiSettings user={makeUser()} />);

    await user.type(screen.getByLabelText(/API key/i), "sk-test-key");
    await user.click(screen.getByRole("button", { name: /Save key/i }));

    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("clears the key field after a successful save (never echoes back)", async () => {
    const user = userEvent.setup();
    render(<AiSettings user={makeUser()} />);

    const keyInput = screen.getByLabelText(/API key/i);
    await user.type(keyInput, "sk-test-key");
    expect(keyInput).toHaveValue("sk-test-key");

    await user.click(screen.getByRole("button", { name: /Save key/i }));

    await waitFor(() => expect(saveAiCredentialsMock).toHaveBeenCalledTimes(1));
    expect(keyInput).toHaveValue("");
  });

  it("renders the backend's 400 detail rather than the generic failure", async () => {
    saveAiCredentialsMock.mockRejectedValueOnce(new Error("Incorrect API key"));
    const user = userEvent.setup();
    render(<AiSettings user={makeUser()} />);

    await user.type(screen.getByLabelText(/API key/i), "sk-bad-key");
    await user.click(screen.getByRole("button", { name: /Save key/i }));

    await waitFor(() =>
      expect(screen.getByText(/Incorrect API key/i)).toBeInTheDocument(),
    );
    // The save button stays enabled (the form is intact for the user to fix
    // the field); a generic "Failed to save AI credentials" must NOT have appeared.
    expect(
      screen.queryByText(/^Failed to save AI credentials$/),
    ).not.toBeInTheDocument();
  });

  it("maps a model/404 detail verbatim", async () => {
    saveAiCredentialsMock.mockRejectedValueOnce(
      new Error("That model isn't available on Groq"),
    );
    const user = userEvent.setup();
    render(<AiSettings user={makeUser()} />);

    // Switch to Groq so the model-placeholder logic matches the test copy.
    await user.click(screen.getByRole("button", { name: /OpenAI/i }));
    await user.click(screen.getByRole("button", { name: /^Groq$/i }));

    await user.type(screen.getByLabelText(/API key/i), "sk-test-key");
    await user.click(screen.getByRole("button", { name: /Save key/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/That model isn't available on Groq/i),
      ).toBeInTheDocument(),
    );
  });

  it("validates the api_key length before calling the action", async () => {
    const user = userEvent.setup();
    render(<AiSettings user={makeUser()} />);

    await user.type(screen.getByLabelText(/API key/i), "short");
    await user.click(screen.getByRole("button", { name: /Save key/i }));

    // Validation prevents the action; the inline RHF error surfaces instead
    // of a generic network failure.
    await waitFor(() =>
      expect(
        screen.getByText(/API key must be at least 8 characters/i),
      ).toBeInTheDocument(),
    );
    expect(saveAiCredentialsMock).not.toHaveBeenCalled();
  });

  it("falls back to the preset default model when the field is blank", async () => {
    // The model schema accepts blank because the submit handler resolves the
    // preset default. This guards against a regression that re-introduces a
    // silent empty-string save.
    const user = userEvent.setup();
    render(<AiSettings user={makeUser()} />);

    await user.type(screen.getByLabelText(/API key/i), "sk-test-key");
    await user.click(screen.getByRole("button", { name: /Save key/i }));

    await waitFor(() => expect(saveAiCredentialsMock).toHaveBeenCalledTimes(1));
    expect(saveAiCredentialsMock).toHaveBeenCalledWith({
      provider: "openai",
      apiKey: "sk-test-key",
      model: "gpt-5.6",
    });
  });
});

describe("remove", () => {
  it("calls the remove action", async () => {
    const user = userEvent.setup();
    render(
      <AiSettings
        user={makeUser({
          has_ai_key: true,
          ai_provider: "openai",
          ai_model: "gpt-5.6",
        })}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Remove key/i }));

    await waitFor(() =>
      expect(removeAiCredentialsMock).toHaveBeenCalledTimes(1),
    );
  });

  it("refreshes the page on a successful remove", async () => {
    const user = userEvent.setup();
    render(
      <AiSettings
        user={makeUser({
          has_ai_key: true,
          ai_provider: "openai",
          ai_model: "gpt-5.6",
        })}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Remove key/i }));

    await waitFor(() =>
      expect(removeAiCredentialsMock).toHaveBeenCalledTimes(1),
    );
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("surfaces the backend's detail on a remove failure", async () => {
    removeAiCredentialsMock.mockRejectedValueOnce(
      new Error("Server rejected the request"),
    );
    const user = userEvent.setup();
    render(
      <AiSettings
        user={makeUser({
          has_ai_key: true,
          ai_provider: "openai",
          ai_model: "gpt-5.6",
        })}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Remove key/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/Server rejected the request/i),
      ).toBeInTheDocument(),
    );
  });
});
