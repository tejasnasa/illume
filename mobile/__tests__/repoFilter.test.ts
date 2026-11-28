import { countLine, filterRepos, statusBucket } from "@/lib/repoFilter";

const repos = [
  { name: "alpha", github_url: "https://github.com/acme/alpha", status: "ready" },
  { name: "beta", github_url: "https://github.com/acme/beta", status: "cloning" },
  { name: "gamma", github_url: "https://github.com/other/gamma", status: "failed" },
];

describe("repoFilter", () => {
  it("buckets statuses", () => {
    expect(statusBucket("ready")).toBe("ready");
    expect(statusBucket("failed")).toBe("failed");
    expect(statusBucket("cloning")).toBe("ingesting");
    expect(statusBucket(undefined)).toBe("ingesting");
  });

  it("matches the name or the URL, ignoring case and padding", () => {
    expect(filterRepos(repos, "  ALPHA ", "all").map((r) => r.name)).toEqual(["alpha"]);
    expect(filterRepos(repos, "acme", "all")).toHaveLength(2);
    expect(filterRepos(repos, "", "all")).toHaveLength(3);
  });

  it("filters by status bucket and combines with the search", () => {
    expect(filterRepos(repos, "", "failed").map((r) => r.name)).toEqual(["gamma"]);
    expect(filterRepos(repos, "acme", "ingesting").map((r) => r.name)).toEqual(["beta"]);
    expect(filterRepos(repos, "zzz", "all")).toEqual([]);
  });

  it("writes the count line", () => {
    expect(countLine(repos)).toBe("3 repositories · 1 ingesting");
    expect(countLine([repos[0]])).toBe("1 repository");
    expect(countLine([])).toBe("0 repositories");
  });
});
