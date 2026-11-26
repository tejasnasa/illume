import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import SystemStatus from "@/components/SystemStatus";
import { server } from "../../../tests/msw/server";

const HEALTH = `${process.env.NEXT_PUBLIC_BACKEND_URL}/healthz`;

describe("SystemStatus", () => {
  it("says all is normal when the probe answers 200", async () => {
    render(<SystemStatus />);

    expect(await screen.findByText("All systems normal")).toBeInTheDocument();
  });

  it("reports a partial outage when the probe answers 503", async () => {
    server.use(
      http.get(HEALTH, () => HttpResponse.json({ status: "degraded" }, { status: 503 })),
    );
    render(<SystemStatus />);

    expect(await screen.findByText("Partial outage")).toBeInTheDocument();
  });

  it("reports the service unreachable when the probe cannot be reached", async () => {
    server.use(http.get(HEALTH, () => HttpResponse.error()));
    render(<SystemStatus />);

    expect(await screen.findByText("Service unreachable")).toBeInTheDocument();
  });
});
