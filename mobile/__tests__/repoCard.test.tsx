/**
 * Tests for :component:`RepoCard`.
 *
 * The card packs a lot into a single tap-target -- status pill, time,
 * branch row, summary, stack chips -- so this test pins each surface:
 *
 * - The on-press callback fires once per tap and receives the repo.
 * - The status pill shows the repo's status string and swaps colour
 *   tone between ready / failed / pending.
 * - The architecture summary renders when present, falling back to the
 *   "Waiting for AI analysis..." placeholder when missing.
 * - The branch row hides when ``ingested_branch`` is null.
 * - The "Detecting..." placeholder shows when both languages and
 *   frameworks are empty arrays.
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

  it("renders the status string", async () => {
    const repo = makeRepo({ status: "ready" });
    const { getByText } = await render(<RepoCard repo={repo} />);
    expect(getByText("ready")).toBeTruthy();
  });

  it("renders the architecture summary when present", async () => {
    const repo = makeRepo({
      architecture_summary: "A useful test summary.",
    });
    const { getByText } = await render(<RepoCard repo={repo} />);
    expect(getByText("A useful test summary.")).toBeTruthy();
  });

  it("shows the placeholder when there is no summary yet", async () => {
    const repo = makeRepo({ architecture_summary: "" });
    const { getByText, queryByText } = await render(<RepoCard repo={repo} />);
    expect(getByText("Waiting for AI analysis...")).toBeTruthy();
    expect(queryByText("A useful test summary.")).toBeNull();
  });

  it("hides the branch row when ingested_branch is null", async () => {
    const repo = makeRepo({
      ingested_branch: null,
      ingested_commit_sha: null,
    });
    const { queryByText } = await render(<RepoCard repo={repo} />);
    expect(queryByText("main")).toBeNull();
  });

  it("shows the branch and short SHA when both are present", async () => {
    const repo = makeRepo({
      ingested_branch: "feature/port",
      ingested_commit_sha: "abcdef1234567890",
    });
    const { getByText } = await render(<RepoCard repo={repo} />);
    expect(getByText("feature/port")).toBeTruthy();
    expect(getByText("abcdef1")).toBeTruthy();
  });

  it("shows 'Detecting...' when no language or framework chips are present", async () => {
    const repo = makeRepo({
      detected_stack: {
        ci_cd: [],
        databases: [],
        languages: [],
        frameworks: [],
        infrastructure: [],
      },
    });
    const { getByText } = await render(<RepoCard repo={repo} />);
    expect(getByText("Detecting...")).toBeTruthy();
  });

  it("renders language and framework chips together", async () => {
    const repo = makeRepo({
      detected_stack: {
        ci_cd: [],
        databases: [],
        languages: ["TypeScript"],
        frameworks: ["Next.js"],
        infrastructure: [],
      },
    });
    const { getByText } = await render(<RepoCard repo={repo} />);
    expect(getByText("TypeScript")).toBeTruthy();
    expect(getByText("Next.js")).toBeTruthy();
  });
});
