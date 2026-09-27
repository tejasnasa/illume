import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import FreeTierBanner from "@/components/FreeTierBanner";
import User from "@/types/user";

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
    free_ingest_used: false,
    free_chat_messages_used: 0,
    ...overrides,
  };
}

describe("visibility", () => {
  it("renders for a fresh keyless user with allowance available", () => {
    render(<FreeTierBanner user={makeUser()} />);

    expect(screen.getByTestId("free-tier-banner")).toBeInTheDocument();
  });

  it("renders while chat allowance remains, even after the free ingest is spent", () => {
    // The chat counter is the one the banner's "kept you around" branch
    // exercises -- the user has burned the single ingestion slot but
    // still has questions left in the budget.
    render(
      <FreeTierBanner
        user={makeUser({
          free_ingest_used: true,
          free_chat_messages_used: 2,
        })}
      />,
    );

    expect(screen.getByTestId("free-tier-banner")).toBeInTheDocument();
  });

  it("does not render when the user has a BYOK key", () => {
    render(
      <FreeTierBanner
        user={makeUser({
          has_ai_key: true,
          ai_provider: "openai",
        })}
      />,
    );

    expect(screen.queryByTestId("free-tier-banner")).not.toBeInTheDocument();
  });

  it("does not render when both allowances are spent", () => {
    render(
      <FreeTierBanner
        user={makeUser({
          free_ingest_used: true,
          free_chat_messages_used: 5,
        })}
      />,
    );

    expect(screen.queryByTestId("free-tier-banner")).not.toBeInTheDocument();
  });
});

describe("copy", () => {
  it("uses the onboarding copy while the free ingest is unused", () => {
    render(<FreeTierBanner user={makeUser()} />);

    expect(screen.getByText(/You're on the free tier/i)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Add your own API key/i }),
    ).toHaveAttribute("href", "/settings");
  });

  it("uses the spent copy once the free ingest is burned", () => {
    render(
      <FreeTierBanner
        user={makeUser({
          free_ingest_used: true,
          free_chat_messages_used: 1,
        })}
      />,
    );

    expect(screen.getByText(/Free Ingestions Used/i)).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: /Add your own API key to continue/i,
      }),
    ).toHaveAttribute("href", "/settings");
  });
});
