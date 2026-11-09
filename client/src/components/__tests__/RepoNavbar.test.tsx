import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RepoNavbar from "@/components/RepoNavbar";
import type Repository from "@/types/repository";

const pathname = vi.hoisted(() => ({ value: "/repo/7" }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathname.value,
}));

vi.mock("@/components/RepoSettings", () => ({
  default: () => <div data-testid="repo-settings" />,
}));

function repo(overrides: Partial<Repository> = {}): Repository {
  return {
    id: "uuid-7",
    name: "acme",
    status: "ready",
    repo_number: 7,
    sync_status: "idle",
    ...overrides,
  } as Repository;
}

describe("RepoNavbar", () => {
  beforeEach(() => {
    pathname.value = "/repo/7";
  });

  it("links to the chat page between Home and Glossary", () => {
    render(<RepoNavbar repo={repo()} />);
    const names = screen
      .getAllByRole("link")
      .map((link) => link.textContent)
      .filter((text) => ["Home", "Chat", "Glossary", "Explorer", "Graph"].includes(text ?? ""));
    expect(names).toEqual(["Home", "Chat", "Glossary", "Explorer", "Graph"]);
    expect(screen.getByRole("link", { name: "Chat" })).toHaveAttribute("href", "/repo/7/chat");
  });

  it("marks Chat as the current page on the chat route", () => {
    pathname.value = "/repo/7/chat";
    render(<RepoNavbar repo={repo()} />);
    expect(screen.getByRole("link", { name: "Chat" }).className).toContain("font-semibold");
    expect(screen.getByRole("link", { name: "Home" }).className).not.toContain("font-semibold");
  });

  it("does not mark Chat on other pages", () => {
    render(<RepoNavbar repo={repo()} />);
    expect(screen.getByRole("link", { name: "Chat" }).className).not.toContain("font-semibold");
  });

  it("shows a placeholder, not a link, while the repository is indexing", () => {
    render(<RepoNavbar repo={repo({ status: "parsing" })} />);
    expect(screen.queryByRole("link", { name: "Chat" })).not.toBeInTheDocument();
    expect(screen.getByText("Chat")).toBeInTheDocument();
  });
});
