/**
 * Compact preset menu that sits inside the chat input, like a model picker.
 * @module PresetPicker
 */
"use client";

import {
  PICKER_PRESETS,
  PRESET_DEFAULTS,
  choiceLabel,
  presetAvailability,
  resolveAuto,
  type Capabilities,
  type PresetChoice,
} from "@/lib/agent/presets";
import {
  CaretUpIcon,
  CheckIcon,
  SlidersHorizontalIcon,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

/**
 * A button showing the current preset, opening a menu of the others.
 *
 * Presets the account cannot run stay in the list, disabled, with the reason as
 * a tooltip and as hidden text so it is also read aloud.
 *
 * @param choice - The selected picker choice.
 * @param caps - What the account can run.
 * @param custom - Whether the drawer has changed the preset's settings.
 * @param disabled - Disables the whole control, as while a run is live.
 * @param onChoice - Called with the chosen preset.
 * @param onOpenDrawer - Opens the advanced drawer.
 * @returns The picker.
 */
export default function PresetPicker({
  choice,
  caps,
  custom,
  disabled = false,
  onChoice,
  onOpenDrawer,
}: {
  choice: PresetChoice;
  caps: Capabilities;
  custom: boolean;
  disabled?: boolean;
  onChoice: (choice: PresetChoice) => void;
  onOpenDrawer: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-(--muted-foreground) hover:bg-(--secondary)/50 hover:text-(--foreground) disabled:opacity-50 disabled:cursor-default cursor-pointer"
      >
        <span data-testid="preset-label">{choiceLabel(choice, caps, custom)}</span>
        <CaretUpIcon size={11} weight="bold" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute bottom-full left-0 z-40 mb-2 w-72 rounded-xl border border-(--border) bg-(--card) p-1.5 shadow-xl backdrop-blur-xl"
        >
          {PICKER_PRESETS.map((preset) => {
            const availability = presetAvailability(preset, caps);
            const target = preset === "auto" ? resolveAuto(caps) : preset;
            const info = PRESET_DEFAULTS[target];
            const selected = choice === preset;
            return (
              <button
                key={preset}
                type="button"
                role="menuitemradio"
                aria-checked={selected}
                disabled={!availability.available}
                aria-disabled={!availability.available}
                title={availability.reason ?? undefined}
                onClick={() => {
                  onChoice(preset);
                  setOpen(false);
                }}
                className="flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left hover:bg-(--secondary)/60 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
              >
                <CheckIcon
                  size={13}
                  weight="bold"
                  className={`mt-0.5 shrink-0 ${selected ? "text-(--chart-1)" : "invisible"}`}
                />
                <span className="min-w-0">
                  <span className="block text-xs font-medium text-(--foreground)">
                    {preset === "auto" ? "Auto" : info.label}
                  </span>
                  {availability.reason && (
                    <span className="sr-only">{availability.reason}</span>
                  )}
                  <span className="block text-[11px] leading-snug text-(--muted-foreground)">
                    {preset === "auto"
                      ? `Picks the best your account can run (${info.label}).`
                      : info.blurb}
                  </span>
                </span>
              </button>
            );
          })}
          <div className="my-1 border-t border-(--border)" />
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onOpenDrawer();
            }}
            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs text-(--foreground) hover:bg-(--secondary)/60 cursor-pointer"
          >
            <SlidersHorizontalIcon size={13} />
            Advanced settings
          </button>
        </div>
      )}
    </div>
  );
}
