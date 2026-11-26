/**
 * Agent settings editor -- the context window agent runs work within.
 * @module AgentSettings
 */
"use client";

import saveAgentSettingsAction from "@/actions/saveAgentSettings";
import User from "@/types/user";
import { agentSettingsSchema } from "@/types/validators";
import { useRouter } from "next/navigation";
import { useState } from "react";
import Button from "./ui/Button";
import Input from "./ui/Input";

/** Used for the placeholder when the server has not sent its default. */
const FALLBACK_CONTEXT_WINDOW = 250_000;

/** Common context windows, offered as one-click choices. */
const PRESETS = [
  { label: "128K", tokens: 128_000 },
  { label: "200K", tokens: 200_000 },
  { label: "400K", tokens: 400_000 },
  { label: "1M", tokens: 1_000_000 },
] as const;

/**
 * Props for the AgentSettings component.
 */
type Props = {
  user: User;
};

/**
 * Renders the agent settings card: the context window, with its own save.
 *
 * Kept apart from the AI credential form so changing the window never asks
 * for the key again. A blank field means the server's default.
 *
 * @param user - Current user; `ai_context_window` seeds the field.
 * @returns The rendered agent settings card.
 */
export default function AgentSettings({ user }: Props) {
  const router = useRouter();
  const [value, setValue] = useState(
    user.ai_context_window == null ? "" : String(user.ai_context_window),
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const fallback = user.ai_context_window_default ?? FALLBACK_CONTEXT_WINDOW;

  /**
   * Validates the field, saves it, and refreshes the server-rendered user so
   * the saved value seeds the next render.
   */
  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaved(false);
    const parsed = agentSettingsSchema.safeParse({ contextWindow: value });
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Invalid value.");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      const contextWindow = parsed.data.contextWindow;
      await saveAgentSettingsAction({
        contextWindow: contextWindow === "" ? null : Number(contextWindow),
      });
      setSaved(true);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      className="flex flex-col gap-4 rounded-md border border-(--border) bg-(--card) p-5"
      onSubmit={handleSubmit}
      noValidate
    >
      <label
        htmlFor="context-window"
        className="font-pixel text-[11px] tracking-[0.12em] text-(--muted-foreground) uppercase"
      >
        Context window · tokens
      </label>
      <div className="flex flex-wrap gap-2">
        {PRESETS.map((preset) => {
          const pressed = value === String(preset.tokens);
          return (
            <button
              key={preset.tokens}
              type="button"
              aria-pressed={pressed}
              onClick={() => {
                setValue(String(preset.tokens));
                setSaved(false);
                setError(null);
              }}
              className={`rounded-sm border px-3.5 py-2.25 font-pixel text-[13px] transition-colors duration-150 hover:cursor-pointer ${
                pressed
                  ? "border-(--accent) bg-(--accent)/8 text-(--foreground)"
                  : "border-white/10 text-zinc-400 hover:text-(--foreground)"
              }`}
            >
              {preset.label}
            </button>
          );
        })}
        <Input
          id="context-window"
          type="text"
          inputMode="numeric"
          autoComplete="off"
          placeholder={fallback.toLocaleString("en-US")}
          aria-invalid={Boolean(error)}
          aria-describedby="context-window-help"
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            setSaved(false);
          }}
          className="w-36"
        />
      </div>
      <p
        id="context-window-help"
        className="m-0 text-[13px] leading-relaxed text-(--muted-foreground)"
      >
        The most input tokens one model call may carry. Set it to your
        model&apos;s context window or lower. When an investigation fills it,
        older tool results are shortened, and the agent answers from what it
        has found if that is not enough. Leave blank for{" "}
        {fallback.toLocaleString("en-US")}.
      </p>
      {error && (
        <p role="alert" className="m-0 text-xs text-red-400">
          {error}
        </p>
      )}

      <div className="flex items-center justify-end gap-3 border-t border-white/6 pt-4">
        {saved && (
          <span className="font-pixel text-xs tracking-[0.06em] text-(--success) uppercase">
            Saved
          </span>
        )}
        <Button type="submit" size="sm" loading={saving}>
          Save
        </Button>
      </div>
    </form>
  );
}
