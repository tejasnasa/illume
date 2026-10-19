/**
 * Tests for the relative-time formatter.
 *
 * The dashboard's :component:`RepoCard` shows ``timeAgo(repo.updated_at)``;
 * the contract is the same string the web helper produces ("3 days
 * ago", "in 5 minutes"). Pinning the output here keeps the two
 * implementations in lock-step -- if the web helper drifts, the strings
 * start to disagree and a test fails rather than a user noticing.
 */

import { timeAgo } from "@/lib/timeAgo";

describe("timeAgo", () => {
  const NOW = new Date("2026-01-15T12:00:00Z");

  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(NOW);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("renders 'Never' for falsy input", () => {
    expect(timeAgo(undefined)).toBe("Never");
    expect(timeAgo(null as unknown as undefined)).toBe("Never");
    expect(timeAgo("")).toBe("Never");
  });

  it("returns 'just now' for sub-five-second deltas", () => {
    expect(timeAgo(new Date("2026-01-15T11:59:58Z"))).toBe("just now");
    expect(timeAgo(new Date("2026-01-15T12:00:00Z"))).toBe("just now");
  });

  it("renders the coarsest fitting bucket for past dates", () => {
    expect(timeAgo(new Date("2026-01-15T11:55:00Z"))).toBe("5 minutes ago");
    expect(timeAgo(new Date("2026-01-15T10:00:00Z"))).toBe("2 hours ago");
    expect(timeAgo(new Date("2026-01-14T12:00:00Z"))).toBe("1 day ago");
    expect(timeAgo(new Date("2026-01-08T12:00:00Z"))).toBe("1 week ago");
    expect(timeAgo(new Date("2025-12-15T12:00:00Z"))).toBe("1 month ago");
    expect(timeAgo(new Date("2025-01-15T12:00:00Z"))).toBe("1 year ago");
  });

  it("uses singular labels for unit-count of one", () => {
    expect(timeAgo(new Date("2026-01-15T11:00:00Z"))).toBe("1 hour ago");
    expect(timeAgo(new Date("2026-01-14T12:00:00Z"))).toBe("1 day ago");
  });

  it("uses plural labels for unit-count above one", () => {
    expect(timeAgo(new Date("2026-01-15T09:00:00Z"))).toBe("3 hours ago");
    expect(timeAgo(new Date("2026-01-13T12:00:00Z"))).toBe("2 days ago");
  });

  it("renders future dates as 'in X units'", () => {
    expect(timeAgo(new Date("2026-01-15T13:00:00Z"))).toBe("in 1 hour");
    expect(timeAgo(new Date("2026-01-15T15:00:00Z"))).toBe("in 3 hours");
  });

  it("accepts ISO-string input", () => {
    expect(timeAgo("2026-01-14T12:00:00Z")).toBe("1 day ago");
  });
});
