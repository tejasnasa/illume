/**
 * Tests for the GitHub URL parser.
 *
 * The parser is the gate on the "external URL" path: a URL that does not
 * match is rejected before any request goes out, and the owner/name it
 * produces is what the branch and commit requests are keyed on.
 */

import {
  GITHUB_REPO_URL_PATTERN,
  INVALID_GITHUB_URL_MESSAGE,
  parseGitHubRepoUrl,
} from "@/lib/githubUrl";

describe("parseGitHubRepoUrl", () => {
  it("splits a plain repository URL", () => {
    expect(parseGitHubRepoUrl("https://github.com/owner/name")).toEqual({
      owner: "owner",
      name: "name",
    });
  });

  it("accepts a trailing slash", () => {
    expect(parseGitHubRepoUrl("https://github.com/owner/name/")).toEqual({
      owner: "owner",
      name: "name",
    });
  });

  it("strips a trailing .git from the repository name", () => {
    expect(parseGitHubRepoUrl("https://github.com/owner/name.git")).toEqual({
      owner: "owner",
      name: "name",
    });
  });

  it("trims surrounding whitespace", () => {
    expect(parseGitHubRepoUrl("  https://github.com/owner/name  ")).toEqual({
      owner: "owner",
      name: "name",
    });
  });

  it("accepts dotted and dashed names", () => {
    expect(parseGitHubRepoUrl("https://github.com/my-org/my.repo.js")).toEqual(
      { owner: "my-org", name: "my.repo.js" },
    );
  });

  it("rejects a non-GitHub host", () => {
    expect(parseGitHubRepoUrl("https://gitlab.com/owner/name")).toBeNull();
  });

  it("rejects a plain http URL", () => {
    expect(parseGitHubRepoUrl("http://github.com/owner/name")).toBeNull();
  });

  it("rejects a URL with no repository segment", () => {
    expect(parseGitHubRepoUrl("https://github.com/owner")).toBeNull();
  });

  it("rejects a URL with a deeper path", () => {
    expect(parseGitHubRepoUrl("https://github.com/owner/name/tree/main")).toBeNull();
  });

  it("rejects an empty string", () => {
    expect(parseGitHubRepoUrl("")).toBeNull();
  });
});

describe("the exported pattern and message", () => {
  it("exposes the pattern the parser uses", () => {
    expect(GITHUB_REPO_URL_PATTERN.test("https://github.com/owner/name")).toBe(
      true,
    );
  });

  it("carries the message the picker shows", () => {
    expect(INVALID_GITHUB_URL_MESSAGE).toContain(
      "https://github.com/user/repo",
    );
  });
});
