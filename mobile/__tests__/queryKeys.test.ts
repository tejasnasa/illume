/**
 * Tests for the centralised query key factory.
 *
 * The factory exists so cache invalidation later in the app has one
 * place to read. These tests pin the shapes -- a renamed key is a
 * silent cache miss for the production app, so a unit test that
 * catches the drift is cheap insurance.
 */

import { queryKeys } from "@/api/queryKeys";

describe("queryKeys", () => {
  it("auth.all is a stable string array", () => {
    expect(queryKeys.auth.all).toEqual(["auth"]);
  });

  it("auth.me extends auth.all", () => {
    expect(queryKeys.auth.me()).toEqual(["auth", "me"]);
  });

  it("repositories.list is stable across calls", () => {
    expect(queryKeys.repositories.list()).toEqual(["repositories", "list"]);
    expect(queryKeys.repositories.list()).toEqual(queryKeys.repositories.list());
  });

  it("repositories.detail scopes by id", () => {
    expect(queryKeys.repositories.detail("abc")).toEqual([
      "repositories",
      "detail",
      "abc",
    ]);
    expect(queryKeys.repositories.detail("xyz")).not.toEqual(
      queryKeys.repositories.detail("abc"),
    );
  });

  it("repositories.graph includes the level", () => {
    expect(queryKeys.repositories.graph("abc", "file")).toEqual([
      "repositories",
      "graph",
      "abc",
      "file",
    ]);
    expect(queryKeys.repositories.graph("abc", "symbol")).not.toEqual(
      queryKeys.repositories.graph("abc", "file"),
    );
  });

  it("repositories.glossary includes page and query", () => {
    expect(queryKeys.repositories.glossary("abc", 0, "")).toEqual([
      "repositories",
      "glossary",
      "abc",
      0,
      "",
    ]);
    expect(queryKeys.repositories.glossary("abc", 1, "auth")).toEqual([
      "repositories",
      "glossary",
      "abc",
      1,
      "auth",
    ]);
  });

  it("github.* keys are deterministic for the same inputs", () => {
    expect(queryKeys.github.myRepos("")).toEqual(["github", "repos", ""]);
    expect(queryKeys.github.branches("foo", "bar")).toEqual([
      "github",
      "branches",
      "foo",
      "bar",
    ]);
    expect(queryKeys.github.commits("foo", "bar", "main")).toEqual([
      "github",
      "commits",
      "foo",
      "bar",
      "main",
    ]);
  });
});
