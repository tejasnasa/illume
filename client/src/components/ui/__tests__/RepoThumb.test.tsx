import { render, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import RepoThumb from "@/components/ui/RepoThumb";
import { server } from "../../../../tests/msw/server";

const REPO_ID = "11111111-1111-1111-1111-111111111111";
const THUMB = `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${REPO_ID}/graph/thumbnail`;

const GRAPH = {
  nodes: [
    { id: "a", path: "src/a.ts", loc: 40, criticality: "safe", fan_in: 1 },
    { id: "b", path: "src/b.ts", loc: 20, criticality: "critical", fan_in: 0 },
  ],
  links: [{ source: "b", target: "a" }],
};

describe("RepoThumb", () => {
  it("swaps the placeholder for a still frame of the real graph", async () => {
    server.use(http.get(THUMB, () => HttpResponse.json(GRAPH)));
    const { container } = render(<RepoThumb repoId={REPO_ID} />);

    expect(container.querySelector("svg")).not.toBeNull();
    await waitFor(() => expect(container.querySelector("canvas")).not.toBeNull());
    expect(container.querySelector("svg")).toBeNull();
  });

  it("keeps the placeholder when the repository has no files to draw", async () => {
    let asked = false;
    server.use(
      http.get(THUMB, () => {
        asked = true;
        return HttpResponse.json({ nodes: [], links: [] });
      }),
    );
    const { container } = render(<RepoThumb repoId={REPO_ID} />);

    await waitFor(() => expect(asked).toBe(true));
    expect(container.querySelector("canvas")).toBeNull();
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("keeps the placeholder when the fetch fails", async () => {
    server.use(http.get(THUMB, () => HttpResponse.json({}, { status: 500 })));
    const { container } = render(<RepoThumb repoId={REPO_ID} />);

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(container.querySelector("canvas")).toBeNull();
  });

  it("fetches nothing for a card that is not ready", async () => {
    // The suite fails any request without a handler, so a fetch here would fail the test.
    const { container } = render(<RepoThumb repoId={REPO_ID} tone="muted" />);

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(container.querySelector("svg")).not.toBeNull();
  });
});
