/**
 * Starter questions for the empty chat, built from the repository's own data.
 * @module AgentSuggestions
 */

/** What the suggestions are built from. */
export interface SuggestionSource {
  name: string;
  /** Entry points as stored: a list of paths, a map keyed by path, or nested. */
  entryPoints: unknown;
  /** Highest-criticality file path, when the guide has one. */
  criticalFile: string | null;
}

/**
 * Pulls a readable entry-point path out of whatever shape was stored.
 *
 * @param value - The stored entry points.
 * @returns The first path-like string found, or `null`.
 */
export function firstEntryPoint(value: unknown): string | null {
  if (typeof value === "string") return value || null;
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = firstEntryPoint(item);
      if (found) return found;
    }
    return null;
  }
  if (value && typeof value === "object") {
    for (const [key, inner] of Object.entries(value)) {
      if (key.includes("/") || key.includes(".")) return key;
      const found = firstEntryPoint(inner);
      if (found) return found;
    }
  }
  return null;
}

/**
 * Three questions worth asking of this repository.
 *
 * @param source - Repository data.
 * @returns Exactly three questions.
 */
export function buildSuggestions(source: SuggestionSource): string[] {
  const entry = firstEntryPoint(source.entryPoints);
  const questions: string[] = [];
  questions.push(
    entry
      ? `Walk me through what happens when ${entry} runs.`
      : `What are the entry points of ${source.name}, and how does a request flow through it?`,
  );
  questions.push(
    source.criticalFile
      ? `Why is ${source.criticalFile} so critical, and what depends on it?`
      : "Which files are the most critical, and what depends on them?",
  );
  questions.push("Where should a new contributor start reading, and why?");
  return questions;
}
