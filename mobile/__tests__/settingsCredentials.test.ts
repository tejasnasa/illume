/**
 * Tests for the BYOK credentials form.
 *
 * The credentials form is the one place a secret crosses the wire, so the
 * rules it has to hold are pinned here:
 *
 * 1. An empty or whitespace-only key is refused before anything is sent.
 * 2. A valid key is sent to the credentials endpoint with the right body.
 * 3. A successful save wipes the key from the form -- the server never
 *    sends it back, and there is no reason to sit on it.
 * 4. The remove action reaches the same endpoint with ``DELETE``.
 *
 * The hook is driven with an injected ``fetchImpl``, so the assertions are
 * about the requests that actually went out rather than about a mock of
 * the transport module.
 */

import { act, renderHook } from "@testing-library/react-native";

import {
  useAiCredentialsForm,
  validateAiCredentials,
} from "@/hooks/useAiCredentialsForm";

const BACKEND = "http://backend.test";
const CREDENTIALS_PATH = `${BACKEND}/api/v1/auth/me/ai-credentials`;

/**
 * A fetch stub that records the requests it was given.
 */
type FetchMock = jest.Mock<Promise<Response>, [string, RequestInit]>;

/**
 * A backend that answers the credentials endpoints.
 *
 * @param status - The status to answer with.
 * @param body - The body to answer with.
 * @returns A fetch stub.
 */
function makeFetch(
  status = 200,
  body: unknown = {
    provider: "openai",
    model: "gpt-4o-mini",
    has_key: true,
    validated_at: null,
  },
): FetchMock {
  return jest.fn<Promise<Response>, [string, RequestInit]>(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  );
}

/**
 * Render the form hook with an injected transport.
 *
 * @param fetchImpl - The fetch stub the requests go through.
 * @returns The rendered hook.
 */
function renderForm(fetchImpl: FetchMock) {
  return renderHook(() =>
    useAiCredentialsForm({
      options: {
        backendUrl: BACKEND,
        fetchImpl: fetchImpl as unknown as typeof fetch,
        getToken: async () => "test-token",
      },
    }),
  );
}

describe("validateAiCredentials", () => {
  it("rejects an empty key", () => {
    const result = validateAiCredentials({
      provider: "openai",
      apiKey: "",
      model: "",
    });

    expect(result.valid).toBe(false);
    expect(result.errors.apiKey).toBe("API key must be at least 8 characters.");
  });

  it("rejects a whitespace-only key", () => {
    const result = validateAiCredentials({
      provider: "openai",
      apiKey: "        ",
      model: "",
    });

    expect(result.valid).toBe(false);
    expect(result.errors.apiKey).toBeTruthy();
  });

  it("rejects a missing provider", () => {
    const result = validateAiCredentials({
      provider: "",
      apiKey: "sk-test-key-123",
      model: "",
    });

    expect(result.valid).toBe(false);
    expect(result.errors.provider).toBe("Pick a provider.");
  });

  it("accepts a valid key and trims it", () => {
    const result = validateAiCredentials({
      provider: "openai",
      apiKey: "  sk-test-key-123  ",
      model: " gpt-5.6 ",
    });

    expect(result.valid).toBe(true);
    expect(result.values?.apiKey).toBe("sk-test-key-123");
    expect(result.values?.model).toBe("gpt-5.6");
  });
});

describe("useAiCredentialsForm", () => {
  it("does not send anything when the key is empty", async () => {
    const fetchImpl = makeFetch();
    const { result } = await renderForm(fetchImpl);

    await act(async () => {
      result.current.setProvider("openai");
    });
    await act(async () => {
      result.current.setApiKey("");
    });

    let saved = true;
    await act(async () => {
      saved = await result.current.onSubmit();
    });

    expect(saved).toBe(false);
    expect(result.current.errors.apiKey).toBeTruthy();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("does not send anything when the key is only whitespace", async () => {
    const fetchImpl = makeFetch();
    const { result } = await renderForm(fetchImpl);

    await act(async () => {
      result.current.setProvider("openai");
    });
    await act(async () => {
      result.current.setApiKey("   \n  ");
    });

    let saved = true;
    await act(async () => {
      saved = await result.current.onSubmit();
    });

    expect(saved).toBe(false);
    expect(result.current.errors.apiKey).toBeTruthy();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("saves a valid key to the credentials endpoint", async () => {
    const fetchImpl = makeFetch();
    const { result } = await renderForm(fetchImpl);

    await act(async () => {
      result.current.setProvider("openai");
    });
    await act(async () => {
      result.current.setApiKey("sk-test-key-123");
    });

    let saved = false;
    await act(async () => {
      saved = await result.current.onSubmit();
    });

    expect(saved).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(CREDENTIALS_PATH);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toEqual({
      provider: "openai",
      api_key: "sk-test-key-123",
      // The model field was left blank, so the provider's default model
      // is what travels.
      model: "gpt-4o-mini",
    });
  });

  it("sends the model the user typed", async () => {
    const fetchImpl = makeFetch();
    const { result } = await renderForm(fetchImpl);

    await act(async () => {
      result.current.setProvider("groq");
    });
    await act(async () => {
      result.current.setApiKey("sk-test-key-123");
    });
    await act(async () => {
      result.current.setModel("llama-3.3-70b");
    });

    await act(async () => {
      await result.current.onSubmit();
    });

    const [, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).model).toBe("llama-3.3-70b");
  });

  it("clears the key from the form once it is saved", async () => {
    const fetchImpl = makeFetch();
    const { result } = await renderForm(fetchImpl);

    await act(async () => {
      result.current.setProvider("openai");
    });
    await act(async () => {
      result.current.setApiKey("sk-test-key-123");
    });

    await act(async () => {
      await result.current.onSubmit();
    });

    expect(result.current.apiKey).toBe("");
    expect(result.current.hasKey).toBe(true);
  });

  it("shows the backend's message when the save is refused", async () => {
    const fetchImpl = makeFetch(400, {
      detail: "Incorrect API key for OpenAI.",
    });
    const { result } = await renderForm(fetchImpl);

    await act(async () => {
      result.current.setProvider("openai");
    });
    await act(async () => {
      result.current.setApiKey("sk-wrong-key-123");
    });

    let saved = true;
    await act(async () => {
      saved = await result.current.onSubmit();
    });

    expect(saved).toBe(false);
    expect(result.current.rootError).toBe("Incorrect API key for OpenAI.");
  });

  it("removes the saved credential", async () => {
    const fetchImpl = makeFetch();
    const { result } = await renderForm(fetchImpl);

    let removed = false;
    await act(async () => {
      removed = await result.current.handleRemove();
    });

    expect(removed).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(CREDENTIALS_PATH);
    expect(init.method).toBe("DELETE");
    expect(result.current.hasKey).toBe(false);
  });
});
