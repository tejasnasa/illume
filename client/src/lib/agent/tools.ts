/**
 * Display helpers for agent tools: names, short argument forms and the live
 * status line.
 * @module AgentTools
 */
import type { RunState, ToolRow } from "./reducer";

/** A short, renderable form of one tool argument. */
export interface ShortArg {
  /** `pattern` renders monospace, `path` as a chip, `query` in quotes. */
  kind: "pattern" | "path" | "query" | "text";
  value: string;
  /** A line range or similar qualifier shown beside the value. */
  extra?: string;
}

const LABELS: Record<string, string> = {
  search_code: "Search code",
  search_symbols: "Find symbols",
  grep_code: "Grep",
  search_history: "Search history",
  read_file: "Read file",
  read_symbol: "Read symbol",
  list_files: "List files",
  list_symbols: "List symbols",
  get_importers: "Importers",
  get_importees: "Imports",
  find_path: "Find path",
  get_cochanged: "Changed together",
  get_file_info: "File info",
  get_glossary: "Glossary",
  get_overview: "Overview",
  finish: "Finish",
};

/** The readable name of a tool; unknown tools are title-cased from their id. */
export function toolLabel(tool: string): string {
  if (LABELS[tool]) return LABELS[tool];
  const spaced = tool.replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/**
 * Reduces a tool call's arguments to the one or two values worth showing.
 *
 * @param tool - Tool id.
 * @param args - Parsed arguments, or `null` when the JSON was cut or invalid.
 * @returns Short argument descriptors in display order.
 */
export function shortArgs(
  tool: string,
  args: Record<string, unknown> | null,
): ShortArg[] {
  if (!args) return [];
  const out: ShortArg[] = [];
  const push = (kind: ShortArg["kind"], value: unknown, extra?: string) => {
    const text = str(value);
    if (text) out.push({ kind, value: text, extra });
  };

  switch (tool) {
    case "grep_code":
      push("pattern", args.pattern);
      push("path", args.path_glob);
      break;
    case "read_file": {
      const start = args.start_line;
      const end = args.end_line;
      const range =
        typeof start === "number" || typeof end === "number"
          ? `L${typeof start === "number" ? start : 1}${typeof end === "number" ? `-${end}` : "+"}`
          : undefined;
      push("path", args.path, range);
      break;
    }
    case "search_code":
    case "search_history":
      push("query", args.query);
      break;
    case "search_symbols":
      push("text", args.name);
      break;
    case "read_symbol":
      push("text", args.name);
      push("path", args.path);
      break;
    case "list_files":
      push("path", args.path_prefix);
      break;
    case "find_path":
      push("path", args.source);
      push("path", args.target);
      break;
    default:
      push("path", args.path);
      push("text", args.term ?? args.name);
  }
  return out;
}

/** Line numbers and a range for a read row, from its arguments. */
export function readRange(row: ToolRow): string | null {
  const start = row.parsed?.start_line;
  const end = row.parsed?.end_line;
  if (typeof start !== "number" && typeof end !== "number") return null;
  return `lines ${typeof start === "number" ? start : 1}${typeof end === "number" ? `-${end}` : " onward"}`;
}

/**
 * The live status line for the activity header.
 *
 * @param state - The run state.
 * @returns A short sentence such as `Reading app/auth.py`.
 */
export function statusLabel(state: RunState): string {
  switch (state.status) {
    case "idle":
      return "Ready";
    case "connecting":
      return "Connecting";
    case "done":
      return "Finished";
    case "cancelled":
      return "Stopped";
    case "error":
      return "Run failed";
    case "connection_lost":
      return "Connection lost";
  }

  switch (state.phase) {
    case "planning":
      return "Planning the investigation";
    case "retrieving":
      return "Searching the codebase";
    case "answering":
      return "Writing the answer";
    case "thinking":
      return "Thinking";
    case "tool": {
      for (let i = state.rows.length - 1; i >= 0; i--) {
        const row = state.rows[i];
        if (row.kind !== "tool" || row.status !== "running") continue;
        const [first] = shortArgs(row.tool, row.parsed);
        switch (row.tool) {
          case "read_file":
            return first ? `Reading ${first.value}` : "Reading a file";
          case "grep_code":
            return "Searching code";
          case "search_code":
          case "search_symbols":
            return "Searching code";
          case "search_history":
            return "Searching history";
          case "finish":
            return "Drafting the answer";
          default:
            return `${toolLabel(row.tool)}`;
        }
      }
      return "Working";
    }
    default:
      return "Working";
  }
}

/** Counts shown beside the status: tools used and distinct sources gathered. */
export function runCounts(state: RunState): { tools: number; sources: number } {
  return {
    tools: state.rows.filter((row) => row.kind === "tool").length,
    sources: Math.max(
      new Set(state.evidenceKeys).size,
      state.citations.length,
    ),
  };
}
