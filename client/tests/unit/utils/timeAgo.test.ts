import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { timeAgo } from "@/utils/timeAgo";

/**
 * The clock is frozen rather than offset per assertion.
 *
 * `timeAgo` reads `new Date()` internally, so every case is expressed as "a date this far
 * before the frozen now". Freezing keeps the arithmetic exact -- a test that computed its
 * own `Date.now()` offset would drift by the milliseconds spent setting itself up, and
 * boundary cases like exactly one minute would flake.
 */
const NOW = new Date("2026-06-15T12:00:00Z");

/** A timestamp `seconds` in the past relative to the frozen clock. */
function secondsAgo(seconds: number): Date {
  return new Date(NOW.getTime() - seconds * 1000);
}

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;
const MONTH = 30 * DAY;
const YEAR = 365 * DAY;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("missing input", () => {
  it("renders undefined as Never", () => {
    expect(timeAgo(undefined)).toBe("Never");
  });

  it("renders an empty string as Never", () => {
    // Falsy rather than "absent": the guard is `if (!dateInput)`, so this is the same
    // branch. Worth pinning because an empty string is otherwise a plausible input.
    expect(timeAgo("")).toBe("Never");
  });
});

describe("recent times", () => {
  it("renders the last few seconds as just now", () => {
    // Below the five-second floor, so the UI never flashes "0 seconds ago".
    expect(timeAgo(secondsAgo(0))).toBe("just now");
    expect(timeAgo(secondsAgo(4))).toBe("just now");
  });

  it("switches to seconds at the boundary", () => {
    expect(timeAgo(secondsAgo(5))).toBe("5 seconds ago");
  });

  it("uses a singular label for one unit", () => {
    expect(timeAgo(secondsAgo(1 * MINUTE))).toBe("1 minute ago");
    expect(timeAgo(secondsAgo(1 * HOUR))).toBe("1 hour ago");
    expect(timeAgo(secondsAgo(1 * DAY))).toBe("1 day ago");
  });

  it("uses a plural label beyond one unit", () => {
    expect(timeAgo(secondsAgo(2 * MINUTE))).toBe("2 minutes ago");
    expect(timeAgo(secondsAgo(3 * HOUR))).toBe("3 hours ago");
    expect(timeAgo(secondsAgo(6 * DAY))).toBe("6 days ago");
  });
});

describe("unit boundaries", () => {
  /**
   * Each case sits one second below the next unit's threshold, so the assertion pins the
   * bucket rather than landing somewhere inside it.
   */
  it.each([
    ["seconds below a minute", MINUTE - 1, "59 seconds ago"],
    ["minutes below an hour", HOUR - 1, "59 minutes ago"],
    ["hours below a day", DAY - 1, "23 hours ago"],
    ["days below a week", WEEK - 1, "6 days ago"],
    ["weeks below a month", MONTH - 1, "4 weeks ago"],
    // Not `YEAR - 1`: a month is 30 days and a year is 365, so 364 days is 12 months by
    // this arithmetic. The top of the month bucket is 12 * MONTH - 1.
    ["months below a year", 12 * MONTH - 1, "11 months ago"],
  ])("renders %s", (_label, seconds, expected) => {
    expect(timeAgo(secondsAgo(seconds))).toBe(expected);
  });

  it("promotes to the next unit exactly at the threshold", () => {
    expect(timeAgo(secondsAgo(MINUTE))).toBe("1 minute ago");
    expect(timeAgo(secondsAgo(HOUR))).toBe("1 hour ago");
    expect(timeAgo(secondsAgo(DAY))).toBe("1 day ago");
    expect(timeAgo(secondsAgo(WEEK))).toBe("1 week ago");
    expect(timeAgo(secondsAgo(MONTH))).toBe("1 month ago");
    expect(timeAgo(secondsAgo(YEAR))).toBe("1 year ago");
  });

  it("counts years for anything older", () => {
    expect(timeAgo(secondsAgo(3 * YEAR))).toBe("3 years ago");
  });
});

describe("future times", () => {
  it("reads forward rather than backward", () => {
    expect(timeAgo(new Date(NOW.getTime() + 2 * HOUR * 1000))).toBe("in 2 hours");
  });

  it("uses a singular label", () => {
    expect(timeAgo(new Date(NOW.getTime() + 1 * DAY * 1000))).toBe("in 1 day");
  });

  it("rounds a sub-second future delta up to one second", () => {
    // Asymmetric with the past, and worth knowing: `Math.floor(-0.2)` is -1, not 0, so
    // 200ms ahead is already one second ahead by the time `absSeconds` is taken. Only the
    // past side has a "just now" floor to fall into, and it applies from exactly zero.
    expect(timeAgo(new Date(NOW.getTime() + 200))).toBe("in 1 second");
  });

  it("renders a whole-second future delta as one second", () => {
    expect(timeAgo(new Date(NOW.getTime() + 1000))).toBe("in 1 second");
  });

  it("does not claim a past tense for a future date", () => {
    expect(timeAgo(new Date(NOW.getTime() + 5 * MINUTE * 1000))).not.toContain("ago");
  });
});

describe("input formats", () => {
  it("accepts a Date", () => {
    expect(timeAgo(secondsAgo(2 * HOUR))).toBe("2 hours ago");
  });

  it("accepts an ISO string", () => {
    expect(timeAgo(secondsAgo(2 * HOUR).toISOString())).toBe("2 hours ago");
  });

  it("throws on an unparseable date", () => {
    // The caller is expected to have validated its input, so this is a programming error
    // rather than something to render.
    expect(() => timeAgo("not-a-date")).toThrow("Invalid date input");
  });

  it("throws rather than rendering NaN", () => {
    expect(() => timeAgo("not-a-date")).not.toThrow(/NaN/);
  });
});
