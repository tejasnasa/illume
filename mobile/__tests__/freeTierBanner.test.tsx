/**
 * Tests for the free-tier banner component.
 *
 * The banner is the only place the app states the user's remaining
 * allowance, so the copy and the link it offers are both contract.
 */

import React from "react";
import { fireEvent, render } from "@testing-library/react-native";
import { router } from "expo-router";

import { FreeTierBanner } from "@/ui/FreeTierBanner";
import type User from "@/types/user";

jest.mock("expo-router", () => {
  function noop() {
    /* router stub */
  }
  const routerObj = {
    push: noop,
    replace: noop,
    back: noop,
    navigate: noop,
  };
  return {
    __esModule: true,
    default: routerObj,
    router: routerObj,
    useRouter: () => routerObj,
    Stack: ((p: { children?: unknown }) => p.children) as unknown as object,
    Redirect: (() => null) as unknown as object,
  };
});

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

beforeEach(() => {
  (router.push as unknown as (...args: string[]) => void) = () => {};
});

describe("FreeTierBanner", () => {
  it("renders for a fresh keyless user with allowance available", async () => {
    const screen = await render(<FreeTierBanner user={makeUser()} />);
    expect(screen.getByTestId("free-tier-banner")).toBeTruthy();
    expect(screen.getByText("You're on the free tier")).toBeTruthy();
  });

  it("counts the slot usage once some ingestions are spent", async () => {
    const screen = await render(
      <FreeTierBanner user={makeUser({ free_ingestions_used: 1 })} />,
    );
    expect(screen.getByText("1 of 3 free ingestions used")).toBeTruthy();
  });

  it("does not render for a BYOK user", async () => {
    const screen = await render(
      <FreeTierBanner
        user={makeUser({ has_ai_key: true, ai_provider: "openai" })}
      />,
    );
    expect(screen.queryByTestId("free-tier-banner")).toBeNull();
  });

  it("does not render when both allowances are spent", async () => {
    const screen = await render(
      <FreeTierBanner
        user={makeUser({
          free_ingestions_used: 3,
          free_chat_messages_used: 10,
        })}
      />,
    );
    expect(screen.queryByTestId("free-tier-banner")).toBeNull();
  });

  it("does not render without a user", async () => {
    const screen = await render(<FreeTierBanner user={null} />);
    expect(screen.queryByTestId("free-tier-banner")).toBeNull();
  });

  it("routes to settings from the call to action", async () => {
    const pushCalls: string[] = [];
    (router.push as unknown as (...args: string[]) => void) = (
      href: string,
    ) => {
      pushCalls.push(href);
    };

    const screen = await render(<FreeTierBanner user={makeUser()} />);
    fireEvent.press(screen.getByTestId("free-tier-cta"));

    expect(pushCalls).toContain("/(app)/settings");
  });
});

/**
 * A trivial assertion that the component's own type is the one the
 * dashboard passes -- the banner takes the full user, not a subset.
 */
describe("FreeTierBanner props", () => {
  it("accepts a full user record", async () => {
    const screen = await render(
      <FreeTierBanner user={makeUser({ free_ingestions_used: 2 })} />,
    );
    expect(screen.getByText("2 of 3 free ingestions used")).toBeTruthy();
  });
});
