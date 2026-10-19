/**
 * Human-readable relative time formatting ("3 days ago").
 *
 * @module TimeAgo
 *
 * Verbatim port of ``client/src/utils/timeAgo.ts`` -- the algorithm and
 * output strings are stable contract; if the web helper ever drifts, the
 * two should be re-aligned rather than diverged.
 */

/**
 * Format a date as relative time (past or future).
 *
 * @param dateInput - Date value, string, or undefined (renders as "Never").
 * @returns Relative description like "2 hours ago", "in 3 days", or "just now".
 */
export const timeAgo = (dateInput: string | Date | undefined): string => {
  if (dateInput === undefined || dateInput === null) return "Never";
  const date = dateInput instanceof Date ? dateInput : new Date(dateInput);
  const now = new Date();
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (isNaN(seconds)) {
    return "Never";
  }

  // Largest-first buckets so the first match is the coarsest fitting unit.
  const intervals: ReadonlyArray<{ label: string; seconds: number }> = [
    { label: "year", seconds: 31536000 },
    { label: "month", seconds: 2592000 },
    { label: "week", seconds: 604800 },
    { label: "day", seconds: 86400 },
    { label: "hour", seconds: 3600 },
    { label: "minute", seconds: 60 },
    { label: "second", seconds: 1 },
  ];

  // Future dates render as "in X units" rather than "X ago".
  if (seconds < 0) {
    const absSeconds = Math.abs(seconds);
    for (const interval of intervals) {
      const count = Math.floor(absSeconds / interval.seconds);
      if (count >= 1) {
        return `in ${count} ${interval.label}${count !== 1 ? "s" : ""}`;
      }
    }
    return "just now";
  }

  // Sub-5s deltas read as "just now" to avoid "0 seconds ago" flicker.
  if (seconds < 5) return "just now";

  for (const interval of intervals) {
    const count = Math.floor(seconds / interval.seconds);
    if (count >= 1) {
      return `${count} ${interval.label}${count !== 1 ? "s" : ""} ago`;
    }
  }

  return "just now";
};
