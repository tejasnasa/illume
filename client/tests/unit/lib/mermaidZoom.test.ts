import { describe, expect, it } from "vitest";
import { fitZoom, naturalWidth } from "@/components/docs/Mermaid";

describe("naturalWidth", () => {
  it("reads the width from the viewBox", () => {
    expect(naturalWidth('<svg viewBox="-8 -8 1234.5 600">')).toBe(1234.5);
    expect(naturalWidth('<svg viewBox="0,0,800,400">')).toBe(800);
  });

  it("is null without a usable viewBox", () => {
    expect(naturalWidth("<svg width='100'>")).toBeNull();
    expect(naturalWidth('<svg viewBox="0 0 0 10">')).toBeNull();
  });
});

describe("fitZoom", () => {
  it("never enlarges a diagram that already fits", () => {
    expect(fitZoom(400, 1400)).toBe(1);
  });

  it("shrinks a wide diagram to the viewport, leaving the gutter", () => {
    const zoom = fitZoom(2000, 1096);
    expect(zoom).toBeCloseTo(0.5);
  });

  it("does not shrink below the minimum zoom", () => {
    expect(fitZoom(100_000, 1000)).toBe(0.25);
  });
});
