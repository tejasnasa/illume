/**
 * Tests for the free-tier banner policy and copy.
 *
 * The banner is the app's only visible statement about the user's
 * remaining allowance, so both the visibility rule and the exact copy
 * are pinned. The copy is contract: the server owns the cap
 * (``app/services/entitlements.py``) and the UI only reports what it
 * was told.
 */

import {
  resolveFreeTierMessage,
  shouldShowFreeTierBanner,
} from "@/lib/freeTier";
import type User from "@/types/user";

/** Build a user with sensible defaults; tests override what they care about. */
function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: "u1",
    name: "Ada",
    email: "a@b",
    avatar_url: null,
    github_id: "1",
    ai_provider: null,
    ai_model: null,
    has_ai_key: false,
    free_ingestions_used: 0,
    free_chat_messages_used: 0,
    free_ingestions_limit: 3,
    free_chat_messages_limit: 10,
    ...overrides,
  };
}

describe("shouldShowFreeTierBanner", () => {
  it("renders for a fresh keyless user with allowance available", () => {
    expect(shouldShowFreeTierBanner(makeUser())).toBe(true);
  });

  it("renders while chat allowance remains, even after the ingestions are spent", () => {
    expect(
      shouldShowFreeTierBanner(
        makeUser({
          free_ingestions_used: 3,
          free_chat_messages_used: 2,
        }),
      ),
    ).toBe(true);
  });

  it("does not render when the user has a BYOK key", () => {
    expect(
      shouldShowFreeTierBanner(
        makeUser({ has_ai_key: true, ai_provider: "openai" }),
      ),
    ).toBe(false);
  });

  it("does not render when both allowances are spent", () => {
    expect(
      shouldShowFreeTierBanner(
        makeUser({
          free_ingestions_used: 3,
          free_chat_messages_used: 10,
        }),
      ),
    ).toBe(false);
  });

  it("treats a counter past the cap as spent", () => {
    expect(
      shouldShowFreeTierBanner(
        makeUser({
          free_ingestions_used: 5,
          free_chat_messages_used: 0,
        }),
      ),
    ).toBe(true);
  });
});

describe("resolveFreeTierMessage", () => {
  it("uses the onboarding copy while the free ingestions are unused", () => {
    const message = resolveFreeTierMessage(makeUser());
    expect(message.title).toBe("You're on the free tier");
    expect(message.ctaLabel).toBe("Add your own API key");
    expect(message.tone).toBe("primary");
  });

  it("counts the slot usage while some ingestions remain", () => {
    const message = resolveFreeTierMessage(
      makeUser({
        free_ingestions_used: 1,
        free_chat_messages_used: 1,
      }),
    );
    expect(message.title).toBe("1 of 3 free ingestions used");
    expect(message.ctaLabel).toBe("Add your own API key");
  });

  it("uses the spent copy once the free ingestions are burned", () => {
    const message = resolveFreeTierMessage(
      makeUser({
        free_ingestions_used: 3,
        free_chat_messages_used: 1,
      }),
    );
    expect(message.title).toBe("Free Ingestions Used");
    expect(message.ctaLabel).toBe("Add your own API key to continue");
    expect(message.tone).toBe("muted");
  });
});
