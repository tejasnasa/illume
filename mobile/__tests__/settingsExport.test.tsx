/**
 * Tests for the ``.illume`` export.
 *
 * The web client hands the bundle to an ``<a download>``; a phone writes
 * the bundle to the cache directory and offers it to the system share
 * sheet. Both steps are pinned here, because a silent no-op in either one
 * looks exactly like a successful export to the user.
 *
 * The file system and the share sheet are mocked at the module boundary:
 * the assertions are about the file that was written and the URL that was
 * shared, not about Expo's internals.
 */

import React from "react";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";

import { ExportIllumeButton } from "@/components/ExportIllumeButton";

const BACKEND = "http://backend.test";

/**
 * A fetch stub that records the requests it was given.
 */
type FetchMock = jest.Mock<Promise<Response>, [string, RequestInit]>;

/** The bundle the backend answers with. */
const BUNDLE = [
  "@@META",
  "repo=illume",
  "url=https://github.com/owner/illume",
  "branch=main",
  "",
].join("\n");

jest.mock("expo-file-system", () => {
  const write = jest.fn();
  const create = jest.fn();
  const files: string[] = [];

  class MockFile {
    uri: string;

    constructor(...parts: unknown[]) {
      const last = parts[parts.length - 1];
      const name = typeof last === "string" ? last : "";
      files.push(name);
      this.uri = `file:///cache/${name}`;
    }

    create(options?: unknown) {
      create(options);
    }

    write(content: string) {
      write(content);
    }
  }

  return {
    File: MockFile,
    Directory: class {},
    Paths: { cache: { uri: "file:///cache" } },
    __write: write,
    __create: create,
    __files: files,
  };
});

jest.mock("expo-sharing", () => ({
  isAvailableAsync: jest.fn(async () => true),
  shareAsync: jest.fn(async () => {}),
}));

/**
 * The mocked file system, with the spies the assertions read.
 */
const fileSystem = jest.requireMock("expo-file-system") as {
  __write: jest.Mock;
  __create: jest.Mock;
  __files: string[];
};

/**
 * The mocked share sheet, with the spies the assertions read.
 */
const sharing = jest.requireMock("expo-sharing") as {
  isAvailableAsync: jest.Mock;
  shareAsync: jest.Mock;
};

/**
 * Render the button with an injected transport.
 *
 * @param fetchImpl - The fetch stub the export goes through.
 * @returns The rendered button.
 */
async function renderButton(fetchImpl: FetchMock) {
  return render(
    <ExportIllumeButton
      repoId="repo-uuid-1"
      options={{
        backendUrl: BACKEND,
        fetchImpl: fetchImpl as unknown as typeof fetch,
        getToken: async () => "test-token",
      }}
    />,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  fileSystem.__files.length = 0;
  sharing.isAvailableAsync.mockResolvedValue(true);
  sharing.shareAsync.mockResolvedValue(undefined);
});

describe("ExportIllumeButton", () => {
  it("writes the bundle to a file and opens the share sheet", async () => {
    const fetchImpl = jest.fn<Promise<Response>, [string, RequestInit]>(
      async () =>
        new Response(BUNDLE, {
          status: 200,
          headers: { "content-type": "text/plain" },
        }),
    );
    const screen = await renderButton(fetchImpl);

    await act(async () => {
      fireEvent.press(screen.getByTestId("export-illume"));
    });

    await waitFor(() => {
      expect(sharing.shareAsync).toHaveBeenCalledTimes(1);
    });

    // The bundle was fetched, then written to the cache directory.
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BACKEND}/api/v1/repository/repo-uuid-1/export/illume`);
    expect(init.method).toBe("GET");

    expect(fileSystem.__create).toHaveBeenCalledWith({ overwrite: true });
    expect(fileSystem.__write).toHaveBeenCalledWith(BUNDLE);
    // The file is named after the repository the bundle names.
    expect(fileSystem.__files).toEqual(["illume.illume"]);

    // And the share sheet was offered that file.
    const [sharedUrl, sharedOptions] = sharing.shareAsync.mock.calls[0] as [
      string,
      { mimeType?: string },
    ];
    expect(sharedUrl).toBe("file:///cache/illume.illume");
    expect(sharedOptions.mimeType).toBe("text/plain");
  });

  it("says so when the device cannot share", async () => {
    sharing.isAvailableAsync.mockResolvedValue(false);

    const fetchImpl = jest.fn<Promise<Response>, [string, RequestInit]>(
      async () =>
        new Response(BUNDLE, {
          status: 200,
          headers: { "content-type": "text/plain" },
        }),
    );
    const screen = await renderButton(fetchImpl);

    await act(async () => {
      fireEvent.press(screen.getByTestId("export-illume"));
    });

    await waitFor(() => {
      expect(
        screen.getByText("Sharing is not available on this device."),
      ).toBeTruthy();
    });
    expect(sharing.shareAsync).not.toHaveBeenCalled();
  });

  it("shows the failure when the export is refused", async () => {
    const fetchImpl = jest.fn<Promise<Response>, [string, RequestInit]>(
      async () =>
        new Response(JSON.stringify({ detail: "Repository is not ready" }), {
          status: 400,
          headers: { "content-type": "application/json" },
        }),
    );
    const screen = await renderButton(fetchImpl);

    await act(async () => {
      fireEvent.press(screen.getByTestId("export-illume"));
    });

    await waitFor(() => {
      expect(screen.getByText("Repository is not ready")).toBeTruthy();
    });
    expect(fileSystem.__write).not.toHaveBeenCalled();
    expect(sharing.shareAsync).not.toHaveBeenCalled();
  });
});
