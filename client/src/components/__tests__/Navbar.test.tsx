import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Navbar from "@/components/Navbar";
import type User from "@/types/user";

vi.mock("@/hooks/useLogout", () => ({ useLogout: () => vi.fn() }));

function user(overrides: Partial<User> = {}): User {
  return {
    id: "u1",
    name: "Ada Lovelace",
    email: "ada@example.com",
    avatar_url: null,
    github_id: "5551234",
    ai_provider: null,
    ai_model: null,
    has_ai_key: false,
    ...overrides,
  } as User;
}

/** Opens the account menu and returns it. */
async function openMenu(): Promise<HTMLElement> {
  await userEvent.setup().click(screen.getByRole("button", { name: "Account menu" }));
  return screen.getByRole("menu", { name: "Account" });
}

describe("account menu", () => {
  it("names the account by name and email, never by the numeric GitHub id", async () => {
    render(<Navbar userData={user()} />);
    const menu = await openMenu();

    expect(within(menu).getByText("Ada Lovelace")).toBeInTheDocument();
    expect(within(menu).getByText("ada@example.com")).toBeInTheDocument();
    expect(within(menu).queryByText(/5551234/)).not.toBeInTheDocument();
  });

  it("falls back to the email when there is no name, without repeating it", async () => {
    render(<Navbar userData={user({ name: "" })} />);
    const menu = await openMenu();

    expect(within(menu).getAllByText("ada@example.com")).toHaveLength(1);
  });

  it("offers settings, contact and log out, but not the dashboard", async () => {
    render(<Navbar userData={user()} />);
    const menu = await openMenu();

    const items = within(menu)
      .getAllByRole("menuitem")
      .map((item) => item.textContent);
    expect(items).toEqual(["Settings", "Contact", "Log out"]);
  });
});
