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

const SECTIONS = ["Overview", "Chat", "Graph", "Explorer", "Glossary"];

describe("RepoNavbar", () => {
  beforeEach(() => {
    pathname.value = "/repo/7";
  });

  /** Section links in the desktop row; the mobile row repeats them. */
  const sectionLinks = () =>
    screen
      .getAllByRole("link")
      .filter((link) => SECTIONS.includes(link.textContent ?? ""))
      .slice(0, SECTIONS.length);

  it("links every section in order, Chat right after the overview", () => {
    render(<RepoNavbar repo={repo()} />);

    expect(sectionLinks().map((link) => link.textContent)).toEqual(SECTIONS);
    for (const chat of screen.getAllByRole("link", { name: "Chat" })) {
      expect(chat).toHaveAttribute("href", "/repo/7/chat");
    }
  });

  it("marks Chat as the current page on the chat route", () => {
    pathname.value = "/repo/7/chat";
    render(<RepoNavbar repo={repo()} />);

    expect(screen.getAllByRole("link", { name: "Chat" })[0]).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      screen.getAllByRole("link", { name: "Overview" })[0],
    ).not.toHaveAttribute("aria-current");
  });

  it("does not mark Chat on other pages", () => {
    render(<RepoNavbar repo={repo()} />);

    expect(
      screen.getAllByRole("link", { name: "Chat" })[0],
    ).not.toHaveAttribute("aria-current");
    expect(screen.getAllByRole("link", { name: "Overview" })[0]).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("links to the repository settings", () => {
    render(<RepoNavbar repo={repo()} />);

    expect(
      screen.getByRole("link", { name: "Repository settings" }),
    ).toHaveAttribute("href", "/repo/7/settings");
  });

  it("shows a placeholder, not a link, while the repository is indexing", () => {
    render(<RepoNavbar repo={repo({ status: "parsing" })} />);
    expect(screen.queryByRole("link", { name: "Chat" })).not.toBeInTheDocument();
    expect(screen.getByText("Chat")).toHaveAttribute("aria-disabled", "true");
  });
});
