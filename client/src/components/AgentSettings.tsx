/**
 * Agent settings editor -- the context window agent runs work within.
 * @module AgentSettings
 */
"use client";

import saveAgentSettingsAction from "@/actions/saveAgentSettings";
import User from "@/types/user";
import { agentSettingsSchema } from "@/types/validators";
import { CheckCircleIcon, GaugeIcon } from "@phosphor-icons/react/dist/ssr";
import { useRouter } from "next/navigation";
import { useState } from "react";
import Button from "./ui/Button";
import Input from "./ui/Input";

/** Used for the placeholder when the server has not sent its default. */
const FALLBACK_CONTEXT_WINDOW = 250_000;

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
      className="rounded-sm border border-(--primary)/20 divide-y divide-(--primary)/10 p-2"
      onSubmit={handleSubmit}
      noValidate
    >
      <div className="px-5 py-3">
        <p className="text-xs font-semibold uppercase tracking-widest text-(--primary)">
          Agent
        </p>
      </div>

      <div className="px-5 py-4 space-y-4">
        <div className="flex flex-col my-4 gap-1">
          <label
            htmlFor="context-window"
            className="text-sm flex items-center gap-1"
          >
            <GaugeIcon size={16} className=" text-(--muted-foreground)" />
            Context window
          </label>
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
          />
          <p
            id="context-window-help"
            className="text-xs text-(--muted-foreground) mt-1"
          >
            The most input tokens one model call may carry. Set it to your
            model&apos;s context window or lower. When an investigation fills
            it, older tool results are shortened, and the agent answers from
            what it has found if that is not enough. Leave blank for{" "}
            {fallback.toLocaleString("en-US")}.
          </p>
          {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
        </div>

        <div className="flex items-center justify-end gap-2 pt-2">
          {saved && (
            <span className="inline-flex items-center gap-1.5 text-xs text-(--chart-1)">
              <CheckCircleIcon size={14} weight="fill" />
              Saved
            </span>
          )}
          <Button type="submit" size="sm" loading={saving} className="gap-1.5">
            <CheckCircleIcon weight="duotone" size={15} />
            Save
          </Button>
        </div>
      </div>
    </form>
  );
}
