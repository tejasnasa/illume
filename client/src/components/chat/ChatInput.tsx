/**
 * Floating chat composer: auto-growing textarea, preset picker and Send/Stop.
 * @module ChatInput
 */
"use client";

import { ArrowUpIcon, StopIcon } from "@phosphor-icons/react";
import { useLayoutEffect, useRef } from "react";

const MAX_HEIGHT_PX = 200;

/**
 * Renders the composer card.
 *
 * Enter sends and Shift+Enter inserts a line break. While a run is live the
 * Send button becomes Stop, which aborts the request.
 *
 * @param value - Current text.
 * @param onChange - Receives edits.
 * @param onSend - Sends the trimmed text.
 * @param onStop - Aborts the live run.
 * @param busy - Whether a run is live.
 * @param disabled - Blocks typing, as when the free allowance is spent.
 * @param placeholder - Placeholder text.
 * @param picker - The preset picker, shown on the left of the action row.
 * @returns The composer.
 */
export default function ChatInput({
  value,
  onChange,
  onSend,
  onStop,
  busy,
  disabled = false,
  placeholder = "Ask about the codebase…",
  picker,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  busy: boolean;
  disabled?: boolean;
  placeholder?: string;
  picker: React.ReactNode;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const canSend = !busy && !disabled && value.trim().length > 0;

  // Grow with the content up to a cap, then scroll inside the field.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
  }, [value]);

  return (
    <div className="w-full rounded-2xl border border-(--border) bg-(--card)/60 p-2 shadow-[0_8px_32px_0_rgb(0_0_0/0.3)] backdrop-blur-xl focus-within:border-(--primary)/40">
      <textarea
        ref={ref}
        value={value}
        rows={1}
        disabled={disabled}
        placeholder={placeholder}
        aria-label="Ask about the codebase"
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            if (canSend) onSend();
          }
        }}
        className="block max-h-50 w-full resize-none bg-transparent px-3 py-2 text-sm text-(--foreground) placeholder:text-(--muted-foreground)/60 focus:outline-none disabled:cursor-not-allowed"
      />
      <div className="flex items-center justify-between px-1 pt-1">
        {picker}
        {busy ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Stop"
            className="flex h-8 w-8 items-center justify-center rounded-full bg-(--foreground) text-(--background) transition-transform hover:scale-105 cursor-pointer"
          >
            <StopIcon size={14} weight="fill" />
          </button>
        ) : (
          <button
            type="button"
            onClick={onSend}
            disabled={!canSend}
            aria-label="Send"
            className="flex h-8 w-8 items-center justify-center rounded-full bg-(--primary) text-(--primary-foreground) transition-all hover:scale-105 disabled:bg-(--primary)/30 disabled:hover:scale-100 disabled:cursor-default cursor-pointer"
          >
            <ArrowUpIcon size={15} weight="bold" />
          </button>
        )}
      </div>
    </div>
  );
}
