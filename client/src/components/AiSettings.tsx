/**
 * BYOK AI credentials editor -- provider, model, and plaintext key.
 * @module AiSettings
 */
"use client";

import useAiCredentialsForm, {
  AiProviderPreset,
} from "@/hooks/useAiCredentialsForm";
import User from "@/types/user";
import { useMemo, useState } from "react";
import Button from "./ui/Button";
import ConfirmBody from "./ui/ConfirmBody";
import Input from "./ui/Input";
import Modal from "./ui/Modal";

/**
 * Provider presets mirrored from the backend's
 * `app/services/llm_providers.py`. Kept inline rather than fetched because
 * the list is small, stable, and used to drive the model placeholder -- a
 * round trip on every render would be the wrong tradeoff.
 */
const PROVIDER_PRESETS: AiProviderPreset[] = [
  { key: "openai", label: "OpenAI", defaultModel: "gpt-5.6" },
  { key: "groq", label: "Groq", defaultModel: "llama-3.3-70b" },
  {
    key: "openrouter",
    label: "OpenRouter",
    defaultModel: "glm/glm-5.3-flash",
  },
  { key: "deepseek", label: "DeepSeek", defaultModel: "deepseek-flash" },
];

/** Small uppercase field label. */
const FIELD_LABEL =
  "font-pixel text-[11px] tracking-[0.12em] text-(--muted-foreground) uppercase";

/**
 * Props for the AiSettings component.
 */
type Props = {
  user: User;
};

/**
 * Renders the BYOK form (provider + key + model) with remove and save
 * actions, plus a status line saying whether a key is connected.
 *
 * Form state and validation live in {@link useAiCredentialsForm}; this
 * component is the visual layer. The provider picker drives the model
 * input's placeholder locally via RHF's `watch` so a switch updates the
 * hint without re-rendering the form tree.
 *
 * @param user - Current user; `ai_provider`, `ai_model`, and `has_ai_key`
 *               seed the form, but the key is never prefilled.
 * @returns The rendered BYOK settings card.
 */
export default function AiSettings({ user }: Props) {
  const {
    register,
    watch,
    setValue,
    errors,
    rootError,
    isSubmitting,
    isRemoving,
    onSubmit,
    handleRemove,
  } = useAiCredentialsForm({
    presets: PROVIDER_PRESETS,
    initialProviderKey: user.ai_provider ?? undefined,
    initialModel: user.ai_model ?? undefined,
  });
  const [showKey, setShowKey] = useState(false);

  // Watch the active provider so the picker highlight and the model
  // placeholder stay in sync without round-tripping through setValue.
  const activeProviderKey = watch("provider");
  const activeModel = watch("model");
  const activePreset = useMemo(
    () => PROVIDER_PRESETS.find((p) => p.key === activeProviderKey),
    [activeProviderKey],
  );

  /**
   * Resolves the model input's placeholder from the active preset. When the
   * user has already typed something, the placeholder is hidden by the
   * browser, so the hint is purely informative on an empty field.
   */
  const modelPlaceholder = useMemo(() => {
    if (activeModel.trim()) return "";
    return activePreset?.defaultModel ?? "";
  }, [activePreset, activeModel]);

  const configured = user.has_ai_key;

  return (
    <form
      className="flex flex-col gap-5 rounded-md border border-(--border) bg-(--card) p-5"
      onSubmit={onSubmit}
      noValidate
    >
      <div className="flex flex-col gap-2.5">
        <span id="ai-provider-label" className={FIELD_LABEL}>
          Provider
        </span>
        <div
          role="radiogroup"
          aria-labelledby="ai-provider-label"
          className="flex flex-wrap self-start overflow-hidden rounded-sm border border-white/10"
        >
          {PROVIDER_PRESETS.map((preset) => {
            const checked = preset.key === activeProviderKey;
            return (
              <button
                key={preset.key}
                type="button"
                role="radio"
                aria-checked={checked}
                onClick={() =>
                  setValue("provider", preset.key, { shouldDirty: true })
                }
                className={`border-l border-white/10 px-3.5 py-2.25 font-pixel text-[13px] transition-colors duration-150 first:border-l-0 hover:cursor-pointer ${
                  checked
                    ? "bg-(--primary) text-pink-50"
                    : "bg-transparent text-zinc-400 hover:text-(--foreground)"
                }`}
              >
                {preset.label}
              </button>
            );
          })}
        </div>
        {errors.provider && (
          <p className="m-0 text-xs text-red-400">{errors.provider.message}</p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
        <div className="flex flex-col gap-2">
          <label htmlFor="api-key" className={FIELD_LABEL}>
            API key
          </label>
          <div className="flex gap-2">
            <Input
              id="api-key"
              type={showKey ? "text" : "password"}
              autoComplete="off"
              spellCheck={false}
              placeholder={
                configured
                  ? "Enter a new key to replace the saved one"
                  : "Paste your provider key"
              }
              aria-invalid={Boolean(errors.apiKey)}
              className="min-w-0 grow"
              {...register("apiKey")}
            />
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-pressed={showKey}
              onClick={() => setShowKey((value) => !value)}
              className="h-11 shrink-0"
            >
              {showKey ? "Hide" : "Show"}
            </Button>
          </div>
          {errors.apiKey && (
            <p className="m-0 text-xs text-red-400">{errors.apiKey.message}</p>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <label htmlFor="model" className={FIELD_LABEL}>
            Model
          </label>
          <Input
            id="model"
            type="text"
            // The literal fallback is the no-provider case: with a preset
            // active, `modelPlaceholder` is that preset's default model.
            placeholder={modelPlaceholder || "Choose a provider first"}
            aria-invalid={Boolean(errors.model)}
            {...register("model")}
          />
          {errors.model && (
            <p className="m-0 text-xs text-red-400">{errors.model.message}</p>
          )}
        </div>
      </div>

      {rootError && (
        <p
          role="alert"
          className="m-0 rounded-sm border border-red-500/25 bg-red-500/8 px-3 py-2.5 text-xs text-red-300"
        >
          {rootError}
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/6 pt-4">
        <span
          className={`inline-flex items-center gap-2 font-pixel text-xs tracking-[0.06em] uppercase ${
            configured ? "text-(--success)" : "text-zinc-500"
          }`}
        >
          <span
            aria-hidden="true"
            className={`size-1.75 ${configured ? "bg-(--success)" : "bg-zinc-600"}`}
          />
          {configured
            ? `Connected${activePreset ? ` · ${activePreset.label}` : ""}`
            : "No key · using the free tier"}
        </span>

        <div className="flex items-center gap-2">
          {configured && (
            <Modal
              className="w-[min(30rem,calc(100vw-2rem))]"
              dialogLabel="Remove API key"
              trigger={
                <Button
                  type="button"
                  size="sm"
                  variant="danger"
                  disabled={isSubmitting || isRemoving}
                >
                  Remove key
                </Button>
              }
            >
              <ConfirmBody
                title="Remove API key"
                danger
                footer={
                  <>
                    <span className="max-w-[55%] text-xs text-red-300">
                      {rootError}
                    </span>
                    <span className="flex gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        data-alert-dialog-close
                        disabled={isRemoving}
                      >
                        Cancel
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        loading={isRemoving}
                        onClick={handleRemove}
                        className="border-none bg-red-500 text-white hover:bg-red-600"
                      >
                        Remove
                      </Button>
                    </span>
                  </>
                }
              >
                <p className="m-0">
                  Illume will delete your saved key and stop using it. You can
                  add a key again at any time.
                </p>
              </ConfirmBody>
            </Modal>
          )}
          <Button
            type="submit"
            size="sm"
            loading={isSubmitting}
            disabled={isRemoving}
          >
            {configured ? "Replace key" : "Save key"}
          </Button>
        </div>
      </div>
    </form>
  );
}
