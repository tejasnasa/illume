/**
 * Tests for the git graph rail layout.
 *
 * The layout decides which rail each commit sits on and where the bezier
 * links run. It is pure geometry, so it is tested without a renderer --
 * the renderer's job is only to draw what this returns.
 *
 * The cases that matter:
 *
 * - A linear history uses a single rail.
 * - A branch adds a second rail, and the merge point returns to the
 *   first.
 * - A commit whose parent is outside the fetched window still gets a
 *   stub, so the rail does not dead-end.
 */

import {
  COLUMN_WIDTH,
  PADDING_X,
  ROW_HEIGHT,
  buildGitGraphLayout,
  getRailColor,
} from "@/lib/gitGraphLayout";

/** Build a commit stub with the given SHA and parents. */
function commit(sha: string, parents: string[] = []) {
  return { sha, parents };
}

describe("buildGitGraphLayout", () => {
  it("puts a linear history on one rail", () => {
    const layout = buildGitGraphLayout([
      commit("c", ["b"]),
      commit("b", ["a"]),
      commit("a", []),
    ]);

    expect(layout.railCount).toBe(1);
    expect(layout.tracks).toEqual([0, 0, 0]);
  });

  it("opens a second rail for a branch and closes it at the merge", () => {
    const layout = buildGitGraphLayout([
      commit("merge", ["main", "feature"]),
      commit("feature", ["base"]),
      commit("main", ["base"]),
      commit("base", []),
    ]);

    // Two rails are live while the branch is open.
    expect(layout.railCount).toBe(2);
    // The merge is on the rail its first parent occupies.
    expect(layout.tracks[0]).toBe(layout.tracks[2]);
    // The branch commit sits on the other rail.
    expect(layout.tracks[1]).not.toBe(layout.tracks[0]);
  });

  it("positions nodes along their rail and down the rows", () => {
    const layout = buildGitGraphLayout([
      commit("c", ["b"]),
      commit("b", ["a"]),
      commit("a", []),
    ]);

    expect(layout.nodes[0].x).toBe(PADDING_X);
    expect(layout.nodes[0].y).toBe(ROW_HEIGHT / 2);
    expect(layout.nodes[2].y).toBe(2 * ROW_HEIGHT + ROW_HEIGHT / 2);
  });

  it("draws one link per parent", () => {
    const layout = buildGitGraphLayout([
      commit("merge", ["main", "feature"]),
      commit("feature", ["base"]),
      commit("main", ["base"]),
      commit("base", []),
    ]);

    // merge -> main, merge -> feature, feature -> base, main -> base.
    expect(layout.links).toHaveLength(4);
  });

  it("draws a stub when the parent is outside the fetched window", () => {
    const layout = buildGitGraphLayout([commit("c", ["missing"])]);

    expect(layout.links).toHaveLength(1);
    // A stub is a straight vertical line, not a bezier.
    expect(layout.links[0].path).not.toContain("C");
  });

  it("sizes the rail area from the number of rails", () => {
    const single = buildGitGraphLayout([commit("a", [])]);
    expect(single.width).toBe(COLUMN_WIDTH + PADDING_X * 2);

    const branched = buildGitGraphLayout([
      commit("merge", ["main", "feature"]),
      commit("feature", ["base"]),
      commit("main", ["base"]),
      commit("base", []),
    ]);
    expect(branched.width).toBe(2 * COLUMN_WIDTH + PADDING_X * 2);
  });

  it("sizes the rail area to the number of commits", () => {
    const layout = buildGitGraphLayout([
      commit("c", ["b"]),
      commit("b", ["a"]),
      commit("a", []),
    ]);
    expect(layout.height).toBe(3 * ROW_HEIGHT);
  });
});

describe("getRailColor", () => {
  it("is stable for the same rail index", () => {
    expect(getRailColor(0)).toBe(getRailColor(0));
  });

  it("cycles the palette", () => {
    expect(getRailColor(6)).toBe(getRailColor(0));
  });

  it("gives different rails different colours", () => {
    expect(getRailColor(0)).not.toBe(getRailColor(1));
  });
});
