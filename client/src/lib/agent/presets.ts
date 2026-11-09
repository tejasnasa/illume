/**
 * Chat presets, their disabled states, advanced overrides and persistence.
 *
 * The server owns the real presets; the defaults mirrored here exist only so the
 * drawer can send the fields that differ from the preset and show "custom" when
 * something does. The server remains the authority: it refuses an override that
 * asks for more than the account may, and that refusal is shown verbatim.
 * @module AgentPresets
 */

/** Presets the server accepts, in the order the drawer lists them. */
export type PresetId =
  | "classic"
  | "hybrid"
  | "hybrid_rerank"
  | "structural"
  | "deep_agent"
  | "deep_agent_workers";

/** The picker's choices: `auto` resolves to one of the presets at send time. */
export type PresetChoice = "auto" | PresetId;

export type ChannelId =
  | "dense"
  | "lexical"
  | "symbol"
  | "grep"
  | "graph"
  | "cochange"
  | "history";

export type RerankId = "none" | "cohere" | "llm" | "jev";
export type TransformId = "identity" | "multi_query" | "hyde";

export const ALL_CHANNELS: ChannelId[] = [
  "dense",
  "lexical",
  "symbol",
  "grep",
  "graph",
  "cochange",
  "history",
];

interface PresetDefaults {
  label: string;
  blurb: string;
  agent: boolean;
  workers: boolean;
  channels: ChannelId[];
  rerank: RerankId;
  transform: TransformId;
  maxIterations: number | null;
  maxWorkers: number | null;
}

const HYBRID_CHANNELS: ChannelId[] = ["dense", "lexical", "symbol"];

export const PRESET_DEFAULTS: Record<PresetId, PresetDefaults> = {
  classic: {
    label: "Classic",
    blurb: "One semantic search, then an answer. Fastest.",
    agent: false,
    workers: false,
    channels: ["dense"],
    rerank: "none",
    transform: "identity",
    maxIterations: null,
    maxWorkers: null,
  },
  hybrid: {
    label: "Hybrid",
    blurb: "Semantic, keyword and symbol search fused together.",
    agent: false,
    workers: false,
    channels: HYBRID_CHANNELS,
    rerank: "none",
    transform: "identity",
    maxIterations: null,
    maxWorkers: null,
  },
  hybrid_rerank: {
    label: "Hybrid + rerank",
    blurb: "Hybrid search, reranked for relevance.",
    agent: false,
    workers: false,
    channels: HYBRID_CHANNELS,
    rerank: "jev",
    transform: "identity",
    maxIterations: null,
    maxWorkers: null,
  },
  structural: {
    label: "Structural",
    blurb: "Adds grep, the import graph, co-change and history.",
    agent: false,
    workers: false,
    channels: ALL_CHANNELS,
    rerank: "jev",
    transform: "identity",
    maxIterations: null,
    maxWorkers: null,
  },
  deep_agent: {
    label: "Deep agent",
    blurb: "An agent that searches and reads the code until it can answer.",
    agent: true,
    workers: false,
    channels: ALL_CHANNELS,
    rerank: "jev",
    transform: "identity",
    maxIterations: 20,
    maxWorkers: null,
  },
  deep_agent_workers: {
    label: "Deep agent + workers",
    blurb: "Splits a broad question across parallel agents.",
    agent: true,
    workers: true,
    channels: ALL_CHANNELS,
    rerank: "jev",
    transform: "identity",
    maxIterations: 20,
    maxWorkers: 4,
  },
};

/** The presets in the picker's menu; the other two live in the drawer. */
export const PICKER_PRESETS: PresetChoice[] = [
  "auto",
  "classic",
  "hybrid",
  "deep_agent",
  "deep_agent_workers",
];

/** What the picker needs to know about the account. */
export interface Capabilities {
  /** The account has its own model key; the free tier cannot run agents. */
  hasOwnKey: boolean;
  /** `false` when the key's model was measured unable to call tools. */
  supportsTools: boolean | null;
}

export interface Availability {
  available: boolean;
  /** Why it is disabled; shown on hover. */
  reason: string | null;
}

/**
 * Whether a preset can run for this account, and why not.
 *
 * @param preset - Preset or `auto`.
 * @param caps - Account capabilities.
 * @returns Availability with a reason when disabled.
 */
export function presetAvailability(
  preset: PresetChoice,
  caps: Capabilities,
): Availability {
  if (preset === "auto") return { available: true, reason: null };
  if (!PRESET_DEFAULTS[preset].agent) return { available: true, reason: null };
  if (!caps.hasOwnKey) {
    return {
      available: false,
      reason:
        "Agent presets run on your own API key. Add one in settings to use them.",
    };
  }
  if (caps.supportsTools === false) {
    return {
      available: false,
      reason:
        "The model behind your API key does not support tool calling, which agent presets need.",
    };
  }
  return { available: true, reason: null };
}

/**
 * Chooses the preset `auto` stands for.
 *
 * @param caps - Account capabilities.
 * @returns The strongest preset this account can run.
 */
export function resolveAuto(caps: Capabilities): PresetId {
  if (!caps.hasOwnKey) return "classic";
  if (caps.supportsTools === false) return "hybrid";
  return "deep_agent";
}

/** The advanced drawer's values. */
export interface DrawerSettings {
  channels: ChannelId[];
  rerank: RerankId;
  transform: TransformId;
  maxWorkers: number;
  maxIterations: number;
}

/**
 * The drawer's values before anything is changed.
 *
 * @param preset - A concrete preset.
 * @returns Settings equal to the preset's own.
 */
export function defaultSettings(preset: PresetId): DrawerSettings {
  const d = PRESET_DEFAULTS[preset];
  return {
    channels: [...d.channels],
    rerank: d.rerank,
    transform: d.transform,
    maxWorkers: d.maxWorkers ?? 4,
    maxIterations: d.maxIterations ?? 12,
  };
}

/** The request body's `overrides`, holding only what differs from the preset. */
export interface Overrides {
  channels?: ChannelId[];
  rerank?: { kind: RerankId };
  query?: { transform: TransformId };
  planner?: { max_workers: number };
  agent?: { max_iterations: number };
}

function sameSet<T>(a: T[], b: T[]): boolean {
  return a.length === b.length && a.every((item) => b.includes(item));
}

/**
 * Computes the overrides for a settings object.
 *
 * @param preset - The concrete preset the run uses.
 * @param settings - Drawer values.
 * @returns The differing fields, or `undefined` when nothing differs.
 */
export function buildOverrides(
  preset: PresetId,
  settings: DrawerSettings,
): Overrides | undefined {
  const base = PRESET_DEFAULTS[preset];
  const out: Overrides = {};

  if (!sameSet(settings.channels, base.channels)) {
    out.channels = settings.channels;
  }
  if (settings.rerank !== base.rerank) {
    out.rerank = { kind: settings.rerank };
  }
  if (settings.transform !== base.transform) {
    out.query = { transform: settings.transform };
  }

  if (base.workers && settings.maxWorkers !== base.maxWorkers) {
    out.planner = { max_workers: settings.maxWorkers };
  }
  if (base.agent && settings.maxIterations !== base.maxIterations) {
    out.agent = { max_iterations: settings.maxIterations };
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

/** Whether the drawer's values differ from the preset's own. */
export function isCustom(
  preset: PresetId,
  settings: DrawerSettings,
): boolean {
  return buildOverrides(preset, settings) !== undefined;
}

/** A remembered choice for one repository. */
export interface StoredChoice {
  preset: PresetChoice;
  settings: DrawerSettings | null;
}

const STORAGE_PREFIX = "illume.chat.preset.";

const VALID_CHOICES = new Set<string>(["auto", ...Object.keys(PRESET_DEFAULTS)]);

/**
 * Reads the choice remembered for a repository.
 *
 * @param repoId - Repository id.
 * @returns The stored choice, or `null` when none is stored or storage fails.
 */
export function loadChoice(repoId: string): StoredChoice | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + repoId);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredChoice>;
    if (!parsed.preset || !VALID_CHOICES.has(parsed.preset)) return null;
    return { preset: parsed.preset, settings: parsed.settings ?? null };
  } catch {
    return null;
  }
}

/**
 * Remembers the choice for a repository; failures are ignored.
 *
 * @param repoId - Repository id.
 * @param choice - Preset and drawer values.
 */
export function saveChoice(repoId: string, choice: StoredChoice): void {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + repoId, JSON.stringify(choice));
  } catch {
    // Storage can be blocked or full; the choice then lasts for the visit only.
  }
}

/** The label the picker shows for a choice. */
export function choiceLabel(
  choice: PresetChoice,
  caps: Capabilities,
  custom: boolean,
): string {
  if (custom) return "Custom";
  if (choice === "auto") return `Auto · ${PRESET_DEFAULTS[resolveAuto(caps)].label}`;
  return PRESET_DEFAULTS[choice].label;
}
