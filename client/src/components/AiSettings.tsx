/**
 * BYOK AI credentials editor -- provider, model, and plaintext key.
 * @module AiSettings
 */
"use client";

import useAiCredentialsForm, {
  AiProviderPreset,
} from "@/hooks/useAiCredentialsForm";
import User from "@/types/user";
import {
  ApertureIcon,
  CheckCircleIcon,
  HandArrowUpIcon,
  KeyIcon,
  SparkleIcon,
  TrashIcon,
} from "@phosphor-icons/react/dist/ssr";
import { useMemo } from "react";
import Button from "./ui/Button";
import Input from "./ui/Input";
import OptionMenu from "./ui/OptionsMenu";

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

/**
 * Props for the AiSettings component.
 */
type Props = {
  user: User;
};

/**
 * Renders the BYOK form (provider + key + model) with remove and save
 * actions, plus a status line confirming when the key was last validated.
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
      className="rounded-sm border border-(--primary)/20 divide-y divide-(--primary)/10 p-2"
      onSubmit={onSubmit}
      noValidate
    >
      <div className="px-5 py-3 flex items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-widest text-(--primary)">
          AI Provider
        </p>
        {configured && (
          <span className="inline-flex items-center gap-1.5 text-xs text-(--chart-1)">
            <CheckCircleIcon size={14} weight="fill" />
            Connected
          </span>
        )}
      </div>

      <div className="px-5 py-4 space-y-4">
        <p className="text-sm text-(--muted-foreground)">
          Power the glossary, reading order, architecture brief, and chat
          answers with your own provider. Embeddings stay on the server to keep
          the search index consistent.
        </p>

        <div className="flex flex-col my-4 gap-1 w-full">
          <label
            htmlFor="ai-provider"
            className="text-sm flex items-center gap-1"
          >
            <HandArrowUpIcon size={16} className=" text-(--muted-foreground)" />
            Provider
          </label>
          <OptionMenu
            size="lg"
            direction="left"
            className="w-full"
            wrapperClassName="block w-full"
            trigger={
              <span className="flex items-center justify-between gap-2 bg-(--card) text-sm px-3 py-3 border-(--border) border rounded-sm w-full h-11">
                <span className="inline-flex items-center gap-2">
                  <SparkleIcon size={14} weight="duotone" />
                  {activePreset?.label ?? "Select a provider"}
                </span>
                <span className="text-(--muted-foreground)">▾</span>
              </span>
            }
            items={PROVIDER_PRESETS.map((preset) => ({
              label: preset.label,
              disabled: preset.key === activeProviderKey,
              onClick: () => {
                setValue("provider", preset.key, { shouldDirty: true });
              },
            }))}
          />
        </div>

        <div className="flex flex-col my-4 gap-1">
          <label htmlFor="api-key" className="text-sm flex items-center gap-1">
            <KeyIcon size={16} className=" text-(--muted-foreground)" />
            API Key
          </label>
          <Input
            id="api-key"
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder={
              configured
                ? "Enter a new key to replace the saved one"
                : "Paste your provider key"
            }
            aria-label="API key"
            aria-invalid={Boolean(errors.apiKey)}
            {...register("apiKey")}
          />
          {errors.apiKey && (
            <p className="text-xs text-red-400 mt-1">{errors.apiKey.message}</p>
          )}
        </div>

        <div className="flex flex-col my-4 gap-1">
          <label htmlFor="model" className="text-sm flex items-center gap-1">
            <ApertureIcon size={16} className=" text-(--muted-foreground)" />
            Model
          </label>
          <Input
            id="model"
            type="text"
            placeholder={modelPlaceholder || "e.g. gpt-5.6"}
            aria-label="Model"
            aria-invalid={Boolean(errors.model)}
            {...register("model")}
          />
          {errors.model && (
            <p className="text-xs text-red-400 mt-1">{errors.model.message}</p>
          )}
        </div>

        {rootError && (
          <div className="p-3 rounded bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
            {rootError}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 pt-2">
          {configured && (
            <Button
              type="button"
              size="sm"
              loading={isRemoving}
              disabled={isSubmitting}
              onClick={handleRemove}
              className="border-red-500 bg-white text-red-500 hover:border-red-700 border-2 gap-1.5"
            >
              <TrashIcon weight="duotone" size={15} />
              Remove key
            </Button>
          )}
          <Button
            type="submit"
            size="sm"
            loading={isSubmitting}
            disabled={isRemoving}
            className="gap-1.5"
          >
            <CheckCircleIcon weight="duotone" size={15} />
            {configured ? "Replace key" : "Save key"}
          </Button>
        </div>
      </div>
    </form>
  );
}
