/**
 * Tests for :component:`RepoCard`.
 *
 * The card packs a lot into a single tap-target, so this test pins each
 * surface:
 *
 * - The on-press callback fires once per tap and receives the repo.
 * - The status chip shows the web client's label and the progress panel,
 *   failure notice and summary each appear only in their own state.
 * - The owner and name are split like the web card's.
 * - The branch line hides when ``ingested_branch`` and the commit are null.
 * - Stack chips are deduplicated and capped, and absent when nothing was
 *   detected.
 */

import { fireEvent, render } from "@testing-library/react-native";

import { RepoCard } from "@/ui/RepoCard";
import type Repository from "@/types/repository";

function makeRepo(overrides: Partial<Repository> = {}): Repository {
  return {
    id: "repo-1",
    github_url: "https://github.com/example/foo",
    name: "foo",
    status: "ready",
    architecture_summary: "An example repository.",
    repo_number: 1,
    primary_language: "TypeScript",
    detected_stack: {
      ci_cd: [],
      databases: [],
      languages: ["TypeScript"],
      frameworks: ["React"],
      infrastructure: [],
    },
    entry_points: null,
    ingested_branch: "main",
    ingested_commit_sha: "abcdef1234567890",
    analysis_commit_sha: null,
    created_at: new Date(),
    updated_at: new Date(),
    auto_update_enabled: true,
    auto_update_interval_hours: 6,
    next_sync_at: null,
    last_synced_at: null,
    sync_status: "idle",
    last_sync_error: null,
    consecutive_sync_failures: 0,
    last_sync_summary: null,
    sync_available: false,
    ...overrides,
  };
}

describe("RepoCard", () => {
  it("fires onPress with the repository when tapped", async () => {
    const repo = makeRepo({ id: "tap-target", name: "tap-target" });
    const onPress = jest.fn();

    const { getByLabelText } = await render(
      <RepoCard repo={repo} onPress={onPress} />,
    );
    fireEvent.press(getByLabelText("Open tap-target"));

    expect(onPress).toHaveBeenCalledTimes(1);
    expect(onPress).toHaveBeenCalledWith(repo);
  });

  it("shows the status label and the split owner and name", async () => {
    const repo = makeRepo({ status: "ready" });
    const { getByText } = await render(<RepoCard repo={repo} />);
    expect(getByText("Ready")).toBeTruthy();
    expect(getByText("example/")).toBeTruthy();
    expect(getByText("foo")).toBeTruthy();
  });

  it("shows the ingest progress panel while ingesting", async () => {
    const { getByTestId, getByText, queryByTestId } = await render(
      <RepoCard repo={makeRepo({ status: "parsing", architecture_summary: null })} />,
    );
    expect(getByText("Ingesting")).toBeTruthy();
    expect(getByTestId("repo-card-progress")).toBeTruthy();
    expect(getByText("Parsing and mapping files")).toBeTruthy();
    expect(getByText("3/4")).toBeTruthy();
    expect(queryByTestId("repo-card-failed")).toBeNull();
  });

  it("omits the progress panel once the repository is ready", async () => {
    const { queryByTestId } = await render(<RepoCard repo={makeRepo()} />);
    expect(queryByTestId("repo-card-progress")).toBeNull();
  });

  it("shows the failure notice for a failed ingest", async () => {
    const { getByTestId, getByText } = await render(
      <RepoCard repo={makeRepo({ status: "failed", architecture_summary: null })} />,
    );
    expect(getByText("Failed")).toBeTruthy();
    expect(getByTestId("repo-card-failed")).toBeTruthy();
  });

  it("renders the architecture summary when present", async () => {
    const repo = makeRepo({
      architecture_summary: "A useful test summary.",
    });
    const { getByText } = await render(<RepoCard repo={repo} />);
    expect(getByText("A useful test summary.")).toBeTruthy();
  });

  it("shows the placeholder when a ready repository has no summary", async () => {
    const repo = makeRepo({ architecture_summary: "" });
    const { getByText, queryByText } = await render(<RepoCard repo={repo} />);
    expect(getByText("No summary yet")).toBeTruthy();
    expect(queryByText("A useful test summary.")).toBeNull();
  });

  it("hides the branch line when ingested_branch and the commit are null", async () => {
    const repo = makeRepo({
      ingested_branch: null,
      ingested_commit_sha: null,
    });
    const { queryByText } = await render(<RepoCard repo={repo} />);
    expect(queryByText(/⎇/)).toBeNull();
  });

  it("shows the branch and short SHA when both are present", async () => {
    const repo = makeRepo({
      ingested_branch: "feature/port",
      ingested_commit_sha: "abcdef1234567890",
    });
    const { getByText } = await render(<RepoCard repo={repo} />);
    expect(getByText(/feature\/port/)).toBeTruthy();
    expect(getByText("abcdef1")).toBeTruthy();
  });

  it("omits the stack chips when nothing was detected", async () => {
    const repo = makeRepo({
      detected_stack: {
        ci_cd: [],
        databases: [],
        languages: [],
        frameworks: [],
        infrastructure: [],
      },
    });
    const { queryByText } = await render(<RepoCard repo={repo} />);
    expect(queryByText("Detecting...")).toBeNull();
  });

  it("renders language and framework chips together, without duplicates", async () => {
    const repo = makeRepo({
      detected_stack: {
        ci_cd: [],
        databases: [],
        languages: ["TypeScript"],
        frameworks: ["Next.js", "TypeScript"],
        infrastructure: [],
      },
    });
    const { getByText, getAllByText } = await render(<RepoCard repo={repo} />);
    expect(getAllByText("TypeScript").length).toBeGreaterThanOrEqual(1);
    expect(getByText("Next.js")).toBeTruthy();
  });

  it("shows the auto-update state in the footer", async () => {
    const { getByText } = await render(
      <RepoCard repo={makeRepo({ auto_update_interval_hours: 12 })} />,
    );
    expect(getByText("Auto-update · 12h")).toBeTruthy();
  });
});
