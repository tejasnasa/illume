/**
 * Tests for the graph's colour and size rules.
 *
 * These are the web client's formulas, carried over unchanged: the graph is
 * the one place where a colour carries meaning, and a different mapping on
 * the phone would make the two clients disagree about the same repository.
 */

import {
  NODE_COLOR_CAUTION,
  NODE_COLOR_CRITICAL,
  NODE_COLOR_SAFE,
  criticalityColor,
  nodeRadius,
} from "@/lib/graphTypes";

describe("graph colours", () => {
  it("colours a critical node red", () => {
    expect(criticalityColor("critical")).toBe(NODE_COLOR_CRITICAL);
  });

  it("colours a node needing caution yellow", () => {
    expect(criticalityColor("caution")).toBe(NODE_COLOR_CAUTION);
  });

  it("colours everything else green", () => {
    expect(criticalityColor("safe")).toBe(NODE_COLOR_SAFE);
    expect(criticalityColor("unknown")).toBe(NODE_COLOR_SAFE);
    expect(criticalityColor(null)).toBe(NODE_COLOR_SAFE);
    expect(criticalityColor(undefined)).toBe(NODE_COLOR_SAFE);
  });
});

describe("graph node size", () => {
  it("scales the radius with the square root of the lines of code", () => {
    expect(nodeRadius(400)).toBeCloseTo(10);
    expect(nodeRadius(100)).toBeCloseTo(5);
  });

  it("never goes below the floor for an empty file", () => {
    expect(nodeRadius(0)).toBeCloseTo(Math.sqrt(10) * 0.5);
    expect(nodeRadius(-5)).toBeCloseTo(Math.sqrt(10) * 0.5);
  });

  it("scales with the view", () => {
    expect(nodeRadius(100, 2)).toBeCloseTo(10);
  });
});
