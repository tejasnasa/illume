/**
 * Tests for the file detail card.
 *
 * The card's job is to answer "what is this file" at a glance and to get
 * the reader to the source. The second one is the interesting half: the
 * web client links to ``master`` whatever branch the repository was
 * ingested from, so the link is a dead button for most repositories. These
 * tests pin the mobile behaviour -- the link follows the branch the
 * repository was actually indexed at.
 */

import React from "react";
import { Linking } from "react-native";
import { fireEvent, render } from "@testing-library/react-native";

import {
  DEFAULT_SOURCE_BRANCH,
  FileDetailCard,
  buildFileSourceUrl,
} from "@/components/FileDetailCard";
import type { FileNode } from "@/types/explorer";

/**
 * Build the file the card describes.
 *
 * @param overrides - The fields the test cares about.
 * @returns The file entry.
 */
function makeFile(overrides: Partial<FileNode> = {}): FileNode {
  return {
    id: "file-1",
    label: "app.ts",
    path: "src/app.ts",
    group: "src",
    kind: "file",
    loc: 120,
    criticality: "critical",
    language: "TypeScript",
    fan_in: 12,
    fan_out: 3,
    ...overrides,
  };
}

describe("buildFileSourceUrl", () => {
  it("points at the branch the repository was ingested from", () => {
    expect(
      buildFileSourceUrl(
        "https://github.com/example/foo",
        "src/app.ts",
        "main",
      ),
    ).toBe("https://github.com/example/foo/blob/main/src/app.ts");
  });

  it("falls back to master only when there is no branch", () => {
    expect(
      buildFileSourceUrl("https://github.com/example/foo", "src/app.ts", null),
    ).toBe("https://github.com/example/foo/blob/master/src/app.ts");
  });

  it("does not double up the slashes", () => {
    expect(
      buildFileSourceUrl(
        "https://github.com/example/foo/",
        "src/app.ts",
        "develop",
      ),
    ).toBe("https://github.com/example/foo/blob/develop/src/app.ts");
  });

  it("escapes the path but not the branch", () => {
    expect(
      buildFileSourceUrl(
        "https://github.com/example/foo",
        "src/my file.ts",
        "feature/new",
      ),
    ).toBe("https://github.com/example/foo/blob/feature/new/src/my%20file.ts");
  });
});

describe("FileDetailCard", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("renders the file's identity and its metrics", async () => {
    const screen = await render(
      <FileDetailCard
        file={makeFile()}
        githubUrl="https://github.com/example/foo"
        branch="main"
      />,
    );

    expect(screen.getByTestId("file-detail-label")).toHaveTextContent("app.ts");
    expect(screen.getByTestId("file-detail-path")).toHaveTextContent(
      "src/app.ts",
    );
    expect(screen.getByTestId("file-detail-language")).toHaveTextContent(
      "TypeScript",
    );
    expect(screen.getByTestId("file-detail-kind")).toHaveTextContent("file");
    expect(screen.getByTestId("file-detail-criticality")).toHaveTextContent(
      "critical",
    );
    expect(screen.getByTestId("file-detail-loc")).toHaveTextContent("120");
    expect(screen.getByTestId("file-detail-fan-in")).toHaveTextContent("12");
    expect(screen.getByTestId("file-detail-fan-out")).toHaveTextContent("3");
  });

  it("links to the file on the branch the repository was ingested from", async () => {
    const openUrl = jest.spyOn(Linking, "openURL").mockResolvedValue(undefined);

    const screen = await render(
      <FileDetailCard
        file={makeFile()}
        githubUrl="https://github.com/example/foo"
        branch="main"
      />,
    );

    fireEvent.press(screen.getByTestId("file-detail-github-link"));

    expect(openUrl).toHaveBeenCalledWith(
      "https://github.com/example/foo/blob/main/src/app.ts",
    );
    // The card says which branch the link points at, so a reader can tell
    // a live link from a stale one.
    expect(screen.getByTestId("file-detail-branch")).toHaveTextContent("main");
  });

  it("never hard-codes master over a real branch", async () => {
    const openUrl = jest.spyOn(Linking, "openURL").mockResolvedValue(undefined);
    // The spy is restored between tests, but its call history is not
    // guaranteed to be: start from a clean one so the assertion below is
    // about this test's press and nothing else.
    openUrl.mockClear();

    const screen = await render(
      <FileDetailCard
        file={makeFile()}
        githubUrl="https://github.com/example/foo"
        branch="trunk"
      />,
    );

    fireEvent.press(screen.getByTestId("file-detail-github-link"));

    const url = openUrl.mock.calls[0][0] as string;
    expect(url).toBe("https://github.com/example/foo/blob/trunk/src/app.ts");
    expect(url).not.toContain("master");
  });

  it("falls back to master when the repository records no branch", async () => {
    const openUrl = jest.spyOn(Linking, "openURL").mockResolvedValue(undefined);

    const screen = await render(
      <FileDetailCard
        file={makeFile()}
        githubUrl="https://github.com/example/foo"
        branch={null}
      />,
    );

    fireEvent.press(screen.getByTestId("file-detail-github-link"));

    expect(openUrl).toHaveBeenCalledWith(
      `https://github.com/example/foo/blob/${DEFAULT_SOURCE_BRANCH}/src/app.ts`,
    );
  });
});
