/**
 * Slide-in drawer with the knobs behind a preset.
 * @module AdvancedDrawer
 */
"use client";

import {
  ALL_CHANNELS,
  PRESET_DEFAULTS,
  defaultSettings,
  isCustom,
  presetAvailability,
  type Capabilities,
  type ChannelId,
  type DrawerSettings,
  type PresetId,
  type RerankId,
  type TransformId,
} from "@/lib/agent/presets";
import { XIcon } from "@phosphor-icons/react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { createPortal } from "react-dom";
import Select from "../ui/Select";

const RERANKERS: { value: RerankId; label: string }[] = [
  { value: "none", label: "None" },
  { value: "cohere", label: "Cohere" },
  { value: "llm", label: "Language model" },
  { value: "jev", label: "Jev" },
];

const TRANSFORMS: { value: TransformId; label: string }[] = [
  { value: "identity", label: "As typed" },
  { value: "multi_query", label: "Multi-query" },
  { value: "hyde", label: "HyDE" },
];

const PRESET_ORDER: PresetId[] = [
  "classic",
  "hybrid",
  "hybrid_rerank",
  "structural",
  "deep_agent",
  "deep_agent_workers",
];

/**
 * The advanced settings panel.
 *
 * Without an API key of the account's own, the server only lets a run get
 * cheaper, so options that would add work are disabled rather than offered and
 * refused.
 *
 * @param open - Whether the drawer is showing.
 * @param preset - The concrete preset being tuned.
 * @param settings - Current values.
 * @param caps - What the account can run.
 * @param onClose - Closes the drawer.
 * @param onPreset - Switches the preset (and resets the values to its own).
 * @param onChange - Receives the next settings.
 * @returns The drawer.
 */
export default function AdvancedDrawer({
  open,
  preset,
  settings,
  caps,
  onClose,
  onPreset,
  onChange,
}: {
  open: boolean;
  preset: PresetId;
  settings: DrawerSettings;
  caps: Capabilities;
  onClose: () => void;
  onPreset: (preset: PresetId) => void;
  onChange: (settings: DrawerSettings) => void;
}) {
  const reduced = useReducedMotion();
  const base = PRESET_DEFAULTS[preset];
  const own = caps.hasOwnKey;
  const custom = isCustom(preset, settings);

  const set = <K extends keyof DrawerSettings>(key: K, value: DrawerSettings[K]) =>
    onChange({ ...settings, [key]: value });

  const toggleChannel = (channel: ChannelId) => {
    const has = settings.channels.includes(channel);
    if (has && settings.channels.length === 1) return;
    set(
      "channels",
      has
        ? settings.channels.filter((c) => c !== channel)
        : [...settings.channels, channel],
    );
  };

  // Rendered into the body: the chat page is a fixed layer of its own, and
  // inside it the drawer would sit under the sticky navbar.
  if (typeof document === "undefined") return null;
  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 z-60 bg-black/50 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            aria-hidden="true"
          />
          <motion.aside
            role="dialog"
            aria-label="Advanced chat settings"
            className="fixed inset-y-0 right-0 z-70 flex w-full max-w-sm flex-col border-l border-(--border) bg-(--card)/95 backdrop-blur-xl"
            initial={reduced ? { opacity: 0 } : { x: "100%" }}
            animate={reduced ? { opacity: 1 } : { x: 0 }}
            exit={reduced ? { opacity: 0 } : { x: "100%" }}
            transition={{ duration: 0.25, ease: [0.32, 0.72, 0, 1] }}
          >
            <header className="flex items-center justify-between border-b border-(--border) px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold">Advanced settings</h2>
                <p className="text-[11px] text-(--muted-foreground)" data-testid="drawer-preset-name">
                  Preset: {custom ? "custom" : base.label}
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close advanced settings"
                className="rounded-md p-1.5 text-(--muted-foreground) hover:bg-(--secondary)/60 cursor-pointer"
              >
                <XIcon size={16} />
              </button>
            </header>

            <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4 custom-scrollbar">
              {!own && (
                <p className="rounded-md border border-(--border) bg-(--secondary)/30 p-2 text-[11px] text-(--muted-foreground)">
                  On the free tier a run can only be made cheaper. Add your own
                  API key in settings to add channels.
                </p>
              )}

              <Select
                id="drawer-preset"
                label="Base preset"
                compact
                value={preset}
                onChange={(next) => onPreset(next as PresetId)}
                options={PRESET_ORDER.map((id) => {
                  const availability = presetAvailability(id, caps);
                  return {
                    value: id,
                    label: PRESET_DEFAULTS[id].label,
                    disabled: !availability.available,
                    reason: availability.reason ?? undefined,
                  };
                })}
              />

              <fieldset className="space-y-2">
                <legend className="mb-1 text-xs font-medium">Channels</legend>
                <div className="grid grid-cols-2 gap-1.5">
                  {ALL_CHANNELS.map((channel) => {
                    const on = settings.channels.includes(channel);
                    const locked = !own && !on && !base.channels.includes(channel);
                    return (
                      <label
                        key={channel}
                        className={`flex items-center gap-2 rounded-md border border-(--border) px-2 py-1.5 text-xs ${locked ? "opacity-40" : "cursor-pointer hover:bg-(--secondary)/40"}`}
                      >
                        <input
                          type="checkbox"
                          checked={on}
                          disabled={locked}
                          onChange={() => toggleChannel(channel)}
                          className="accent-(--chart-1)"
                        />
                        {channel}
                      </label>
                    );
                  })}
                </div>
              </fieldset>

              <Select
                id="drawer-rerank"
                label="Reranker"
                compact
                value={settings.rerank}
                onChange={(next) => set("rerank", next as RerankId)}
                options={RERANKERS.map((option) => ({
                  ...option,
                  disabled:
                    !own && option.value !== "none" && option.value !== base.rerank,
                  reason: "Needs your own API key",
                }))}
              />

              <Select
                id="drawer-transform"
                label="Query rewriting"
                compact
                value={settings.transform}
                onChange={(next) => set("transform", next as TransformId)}
                options={TRANSFORMS.map((option) => ({
                  ...option,
                  disabled:
                    !own &&
                    option.value !== "identity" &&
                    option.value !== base.transform,
                  reason: "Needs your own API key",
                }))}
              />

              {base.workers && (
                <label className="block space-y-1.5 text-xs">
                  <span className="font-medium">Workers: {settings.maxWorkers}</span>
                  <input
                    type="range"
                    min={2}
                    max={base.maxWorkers ?? 4}
                    value={settings.maxWorkers}
                    // The server caps budgets at the most generous preset's value.
                    onChange={(event) => set("maxWorkers", Number(event.target.value))}
                    className="w-full accent-(--chart-1)"
                  />
                </label>
              )}

              {base.agent && (
                <label className="block space-y-1.5 text-xs">
                  <span className="font-medium">Iteration cap: {settings.maxIterations}</span>
                  <input
                    type="range"
                    min={1}
                    max={base.maxIterations ?? 20}
                    value={settings.maxIterations}
                    onChange={(event) => set("maxIterations", Number(event.target.value))}
                    className="w-full accent-(--chart-1)"
                  />
                </label>
              )}
            </div>

            <footer className="flex justify-between border-t border-(--border) px-4 py-3">
              <button
                type="button"
                onClick={() => onChange(defaultSettings(preset))}
                disabled={!custom}
                className="text-xs text-(--muted-foreground) hover:text-(--foreground) disabled:opacity-40 cursor-pointer"
              >
                Reset to preset
              </button>
              <button
                type="button"
                onClick={onClose}
                className="rounded-md bg-(--primary) px-3 py-1.5 text-xs font-medium text-(--primary-foreground) cursor-pointer"
              >
                Done
              </button>
            </footer>
          </motion.aside>
        </>
      )}
    </AnimatePresence>,
    document.body,
  );
}
