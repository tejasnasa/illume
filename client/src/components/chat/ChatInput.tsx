/**
 * Floating chat composer: auto-growing textarea, preset picker and Send/Stop.
 * @module ChatInput
 */
"use client";

import { MAX_QUESTION_CHARS } from "@/lib/agent/limits";
import { useLayoutEffect, useRef } from "react";

const MAX_HEIGHT_PX = 200;

/** Length from which the remaining room is shown. */
const COUNTER_FROM = Math.floor(MAX_QUESTION_CHARS * 0.85);

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
    <div className="flex w-full flex-col gap-2.5 rounded-md border border-(--input) bg-(--card) pt-3 pr-3 pb-2.5 pl-4 shadow-[0_16px_40px_#00000080] focus-within:border-(--accent)">
      <textarea
        ref={ref}
        value={value}
        rows={1}
        maxLength={MAX_QUESTION_CHARS}
        disabled={disabled}
        placeholder={placeholder}
        aria-label="Ask about the codebase"
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (
            event.key === "Enter" &&
            !event.shiftKey &&
            !event.nativeEvent.isComposing
          ) {
            event.preventDefault();
            if (canSend) onSend();
          }
        }}
        className="block max-h-50 w-full resize-none bg-transparent text-[15px] leading-normal text-(--foreground) placeholder:text-(--faint-foreground) focus:outline-none disabled:cursor-not-allowed"
      />
      <div className="flex items-center justify-between gap-2.5">
        {picker}
        {value.length >= COUNTER_FROM && (
          <span
            data-testid="char-count"
            aria-live="polite"
            className={`mr-2 ml-auto font-pixel text-[11px] ${value.length >= MAX_QUESTION_CHARS ? "text-(--destructive)" : "text-(--muted-foreground)"}`}
          >
            {value.length} / {MAX_QUESTION_CHARS}
            {value.length >= MAX_QUESTION_CHARS ? " (limit reached)" : ""}
          </span>
        )}
        {busy ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Stop"
            className="ghost rounded-sm border border-(--input) px-3.5 py-2 font-pixel text-[13px] tracking-[0.04em] text-zinc-300 uppercase hover:cursor-pointer"
          >
            <span aria-hidden="true">■ Stop</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={onSend}
            disabled={!canSend}
            aria-label="Send"
            className="cta rounded-sm bg-(--primary) px-3.5 py-2 font-pixel text-[13px] tracking-[0.04em] text-(--primary-foreground) uppercase hover:cursor-pointer disabled:cursor-default disabled:opacity-40"
          >
            <span aria-hidden="true">Send ↵</span>
          </button>
        )}
      </div>
    </div>
  );
}
