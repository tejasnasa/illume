export const timeAgo = (dateInput: string | Date | undefined) => {
  if (!dateInput) return "Never";
  const date = new Date(dateInput);
  const now = new Date();
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (isNaN(seconds)) {
    throw new Error("Invalid date input");
  }

  const intervals = [
    { label: "year", seconds: 31536000 },
    { label: "month", seconds: 2592000 },
    { label: "week", seconds: 604800 },
    { label: "day", seconds: 86400 },
    { label: "hour", seconds: 3600 },
    { label: "minute", seconds: 60 },
    { label: "second", seconds: 1 },
  ];

  if (seconds < 0) {
    const absSeconds = Math.abs(seconds);
    for (const interval of intervals) {
      const count = Math.floor(absSeconds / interval.seconds);
      if (count >= 1) {
        return `in ${count} ${interval.label}${count !== 1 ? "s" : ""}`;
      }
    }
  }

  if (seconds < 5) return "just now";

  for (const interval of intervals) {
    const count = Math.floor(seconds / interval.seconds);
    if (count >= 1) {
      return `${count} ${interval.label}${count !== 1 ? "s" : ""} ago`;
    }
  }

  return "just now";
};
