import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RepositoryPage from "@/app/repo/[id]/page";
import { AmbientBackground, RepoGraphProvider, isChatPath } from "@/components/RepoGraphContext";

const pathname = vi.hoisted(() => ({ value: "/repo/7" }));

vi.mock("next/navigation", () => ({ usePathname: () => pathname.value }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => ({ value: "token" }) }),
  headers: async () => new Headers(),
}));

vi.mock("@/api/repository", () => ({
  GetRepository: async () => ({
    id: "uuid-7",
    name: "acme",
    status: "ready",
    repo_number: 7,
    github_url: "https://github.com/acme/app",
    ingested_branch: "main",
    ingested_commit_sha: "abc1234",
    architecture_summary: "A small web app.",
    detected_stack: {
      languages: ["Python"],
      frameworks: [],
      databases: [],
      infrastructure: [],
      ci_cd: [],
    },
    updated_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
  }),
}));

const guideApi = vi.hoisted(() => ({
  stats: async (): Promise<unknown> => ({
    total_files: 1234,
    total_loc: 98765,
    total_contributors: 7,
    knowledge_silo_count: 3,
    language_breakdown: [
      { language: "python", file_count: 900, loc_count: 75000 },
      { language: "typescript", file_count: 334, loc_count: 23765 },
    ],
  }),
  activity: async (): Promise<unknown> => [
    {
      kind: "pull_request",
      title: "Add token refresh",
      author: "ada",
      at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
      number: 42,
      hash: null,
      files_changed: 5,
    },
    {
      kind: "commit",
      title: "fix: close the session on logout",
      author: "bob",
      at: new Date(Date.now() - 5 * 86_400_000).toISOString(),
      number: null,
      hash: "deadbeefcafe0000",
      files_changed: 1,
    },
  ],
}));

vi.mock("@/api/guide", () => ({
  GetGuide: async () => ({
    architecture_brief: { external_integrations: [] },
    reading_order: [
      { position: 1, file_path: "app/main.py", annotation: "The entry point.", fan_in: 0 },
      { position: 2, file_path: "app/db.py", annotation: "Where data lives.", fan_in: 9 },
    ],
    critical_files: [
      {
        file_path: "app/auth.py",
        criticality: "critical",
        reasons: ["imported by 12 files", "no test coverage"],
        fan_in: 12,
        change_frequency: 30,
        has_tests: false,
      },
    ],
  }),
  GetGuideStats: () => guideApi.stats(),
  GetRecentActivity: () => guideApi.activity(),
}));

const backgroundRenders = vi.hoisted(() => ({ count: 0 }));

vi.mock("@/components/BackgroundGraph", () => ({
  default: () => {
    backgroundRenders.count += 1;
    return <div data-testid="background-graph" />;
  },
}));

describe("repository home page", () => {
  it("keeps the overview and no longer renders the chat", async () => {
    render(await RepositoryPage({ params: Promise.resolve({ id: "7" }) }));
    expect(screen.getByText("AI Architecture Overview")).toBeInTheDocument();
    expect(screen.getByText("Tech Stack Detected")).toBeInTheDocument();
    expect(screen.queryByText(/Chat with Codebase/)).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/Ask about the codebase/)).not.toBeInTheDocument();
  });
});

describe("ambient background", () => {
  const graph = {
    nodes: [],
    links: [],
    metadata: { total_nodes: 0, total_edges: 0, clusters: 0 },
  };

  it("recognises the chat route only", () => {
    expect(isChatPath("/repo/7/chat")).toBe(true);
    expect(isChatPath("/repo/7/chat/")).toBe(true);
    expect(isChatPath("/repo/7")).toBe(false);
    expect(isChatPath("/repo/7/glossary")).toBe(false);
  });

  it("renders on other repo pages", () => {
    pathname.value = "/repo/7/glossary";
    render(
      <RepoGraphProvider graph={graph}>
        <AmbientBackground />
      </RepoGraphProvider>,
    );
    expect(screen.getByTestId("background-graph")).toBeInTheDocument();
  });

  it("is skipped on the chat page, which draws its own graph", () => {
    pathname.value = "/repo/7/chat";
    render(
      <RepoGraphProvider graph={graph}>
        <AmbientBackground />
      </RepoGraphProvider>,
    );
    expect(screen.queryByTestId("background-graph")).not.toBeInTheDocument();
  });

  it("shows the repository at a glance, where to start, and recent activity", async () => {
    render(await RepositoryPage({ params: Promise.resolve({ id: "7" }) }));

    expect(screen.getByText("1.2K")).toBeInTheDocument();
    expect(screen.getByText("98.8K")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Lines by language: python 76%, typescript 24%/ })).toBeInTheDocument();

    const first = screen.getByRole("link", { name: "app/main.py" });
    expect(first).toHaveAttribute("href", "https://github.com/acme/app/blob/abc1234/app/main.py");
    expect(screen.getByText("Where data lives.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Full reading tour/ })).toHaveAttribute("href", "/repo/7/graph");

    expect(screen.queryByText("Handle With Care")).not.toBeInTheDocument();
    expect(screen.getByText("Recent Activity")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add token refresh" })).toHaveAttribute(
      "href",
      "https://github.com/acme/app/pull/42",
    );
    expect(
      screen.getByRole("link", { name: "fix: close the session on logout" }),
    ).toHaveAttribute("href", "https://github.com/acme/app/commit/deadbeefcafe0000");
    expect(screen.getByText("deadbee")).toBeInTheDocument();
  });

  it("leaves recent activity out when it fails to load", async () => {
    guideApi.activity = async () => {
      throw new Error("down");
    };
    render(await RepositoryPage({ params: Promise.resolve({ id: "7" }) }));
    expect(screen.queryByText("Recent Activity")).not.toBeInTheDocument();
    expect(screen.getByText("Start Here")).toBeInTheDocument();
  });

  it("leaves the stats panel out when they fail to load", async () => {
    guideApi.stats = async () => {
      throw new Error("down");
    };
    render(await RepositoryPage({ params: Promise.resolve({ id: "7" }) }));
    expect(screen.queryByText("At a Glance")).not.toBeInTheDocument();
    expect(screen.getByText("Start Here")).toBeInTheDocument();
  });
});
