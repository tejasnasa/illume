/**
 * Form state, validation and submit lifecycle for the BYOK credentials editor.
 *
 * @module UseAiCredentialsForm
 *
 * Port of ``client/src/hooks/useAiCredentialsForm.ts``. The web version
 * drives ``react-hook-form`` with a zod resolver; that library is
 * DOM-oriented and has no place in a React Native bundle, so this keeps the
 * same contract -- validate, submit, surface the failure -- with a
 * hand-rolled state machine over the same zod schema the mobile app already
 * ships (``src/types/validators.ts``).
 *
 * **The key never rests anywhere.** It lives in component state for as long
 * as the form is on screen, it is sent to the backend on save, and it is
 * wiped the moment the save succeeds. It is never written to AsyncStorage
 * or SecureStore, and the server never sends it back -- it answers with
 * whether a key is set, not the key.
 */

import { useCallback, useMemo, useState } from "react";

import {
  removeAiCredentials,
  saveAiCredentials,
  type SettingsRequestOptions,
} from "@/api/settings";
import { ApiError } from "@/lib/apiError";
import { aiCredentialsSchema } from "@/types/validators";

/**
 * One row of the provider preset table.
 *
 * Mirrors the backend's ``app/services/llm_providers.py`` registry. Kept
 * inline rather than fetched: the list is small, stable, and drives the
 * model placeholder, so a round trip on every render would be the wrong
 * trade.
 */
export interface AiProviderPreset {
  /** The provider key the server knows the provider by. */
  key: string;
  /** The name shown to the user. */
  label: string;
  /** The model id used when the user leaves the model field blank. */
  defaultModel: string;
}

/**
 * The providers the backend accepts.
 */
export const AI_PROVIDER_PRESETS: AiProviderPreset[] = [
  { key: "openai", label: "OpenAI", defaultModel: "gpt-4o-mini" },
  { key: "groq", label: "Groq", defaultModel: "llama-3.3-70b-versatile" },
  {
    key: "openrouter",
    label: "OpenRouter",
    defaultModel: "openai/gpt-4o-mini",
  },
  { key: "deepseek", label: "DeepSeek", defaultModel: "deepseek-flash" },
];

/**
 * The three fields the form holds.
 */
export interface AiCredentialsFormValues {
  /** The chosen provider key. */
  provider: string;
  /** The raw API key the user pasted. */
  apiKey: string;
  /** The model id the user typed. May be empty. */
  model: string;
}

/**
 * The per-field validation messages.
 *
 * A key is only present for the fields that failed.
 */
export interface AiCredentialsFormErrors {
  /** Message for the provider field. */
  provider?: string;
  /** Message for the API key field. */
  apiKey?: string;
  /** Message for the model field. */
  model?: string;
}

/**
 * The outcome of validating the form.
 */
export interface AiCredentialsValidation {
  /** True when every field is acceptable. */
  valid: boolean;
  /** The messages for the fields that are not. */
  errors: AiCredentialsFormErrors;
  /**
   * The trimmed values, present only when ``valid`` is true.
   *
   * The schema trims the key and the model, so this is what actually goes
   * over the wire.
   */
  values?: AiCredentialsFormValues;
}

/**
 * Validate the form against the shared schema.
 *
 * Pure and exported so the rules can be exercised without rendering the
 * form.
 *
 * @param values - The current field values.
 * @returns The messages for the invalid fields, plus the trimmed values.
 */
export function validateAiCredentials(
  values: AiCredentialsFormValues,
): AiCredentialsValidation {
  const result = aiCredentialsSchema.safeParse(values);
  if (result.success) {
    return { valid: true, errors: {}, values: result.data };
  }

  const errors: AiCredentialsFormErrors = {};
  for (const issue of result.error.issues) {
    const field = issue.path[0];
    if (typeof field !== "string") continue;
    if (field in errors) continue;
    errors[field as keyof AiCredentialsFormErrors] = issue.message;
  }

  return { valid: false, errors };
}

/**
 * Args for {@link useAiCredentialsForm}.
 */
export interface UseAiCredentialsFormArgs {
  /** The presets to pick from. Defaults to the built-in table. */
  presets?: AiProviderPreset[];
  /** The provider key already saved on the account, if any. */
  initialProviderKey?: string | null;
  /** The model id already saved on the account, if any. */
  initialModel?: string | null;
  /** Whether a key is already saved on the account. */
  hasKey?: boolean;
  /** Transport overrides, so a test can inject a backend and a fetch. */
  options?: SettingsRequestOptions;
  /** Called after a credential was saved successfully. */
  onSaved?: () => void;
  /** Called after the credential was removed successfully. */
  onRemoved?: () => void;
}

/**
 * State and actions returned by {@link useAiCredentialsForm}.
 */
export interface UseAiCredentialsFormResult {
  /** The chosen provider key. */
  provider: string;
  /** Choose a provider. */
  setProvider: (value: string) => void;
  /** The API key currently in the field. */
  apiKey: string;
  /** Set the API key. */
  setApiKey: (value: string) => void;
  /** The model id currently in the field. */
  model: string;
  /** Set the model id. */
  setModel: (value: string) => void;
  /** The per-field validation messages. */
  errors: AiCredentialsFormErrors;
  /** The failure message from the last request, if any. */
  rootError: string | null;
  /** True while a save is in flight. */
  isSubmitting: boolean;
  /** True while a removal is in flight. */
  isRemoving: boolean;
  /** Whether a key is currently stored on the account. */
  hasKey: boolean;
  /** Validate and save the credential. */
  onSubmit: () => Promise<boolean>;
  /** Remove the stored credential. */
  handleRemove: () => Promise<boolean>;
  /** Dismiss the current request failure. */
  clearRootError: () => void;
}

/**
 * Pull the message out of a failed request.
 *
 * @param error - The failure the request raised.
 * @param fallback - The message to use when the failure carries none.
 * @returns The message to show.
 */
function messageOf(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.message) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

/**
 * Manage the BYOK credentials form.
 *
 * @param args - Seed values for the form, the preset table, and optional
 *   transport overrides.
 * @returns The field values, the validation messages and the two actions.
 */
export function useAiCredentialsForm({
  presets = AI_PROVIDER_PRESETS,
  initialProviderKey,
  initialModel,
  hasKey = false,
  options,
  onSaved,
  onRemoved,
}: UseAiCredentialsFormArgs = {}): UseAiCredentialsFormResult {
  const [provider, setProvider] = useState(initialProviderKey ?? "");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(initialModel ?? "");
  const [errors, setErrors] = useState<AiCredentialsFormErrors>({});
  const [rootError, setRootError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRemoving, setIsRemoving] = useState(false);
  const [keyStored, setKeyStored] = useState(hasKey);

  /**
   * Validate the form and, if it holds together, save the credential.
   *
   * @returns True when the credential was saved.
   */
  const onSubmit = useCallback(async (): Promise<boolean> => {
    setRootError(null);

    const validation = validateAiCredentials({ provider, apiKey, model });
    setErrors(validation.errors);
    if (!validation.valid || !validation.values) return false;

    const values = validation.values;
    const preset = presets.find((entry) => entry.key === values.provider);
    // A blank model field falls back to the preset's default model; the
    // schema guarantees the model is a string by the time we get here.
    const resolvedModel = values.model.trim() || preset?.defaultModel || "";

    setIsSubmitting(true);
    try {
      await saveAiCredentials(
        {
          provider: values.provider,
          api_key: values.apiKey,
          model: resolvedModel,
        },
        options,
      );

      // The server never echoes the key back, and there is no reason to sit
      // on it in component state once it has been stored.
      setApiKey("");
      setKeyStored(true);
      onSaved?.();
      return true;
    } catch (error) {
      setRootError(messageOf(error, "Failed to save AI credentials."));
      return false;
    } finally {
      setIsSubmitting(false);
    }
  }, [apiKey, model, onSaved, options, presets, provider]);

  /**
   * Remove the stored credential.
   *
   * @returns True when the credential was removed.
   */
  const handleRemove = useCallback(async (): Promise<boolean> => {
    setRootError(null);
    setIsRemoving(true);
    try {
      await removeAiCredentials(options);

      setApiKey("");
      setProvider("");
      setModel("");
      setErrors({});
      setKeyStored(false);
      onRemoved?.();
      return true;
    } catch (error) {
      setRootError(messageOf(error, "Failed to remove AI credentials."));
      return false;
    } finally {
      setIsRemoving(false);
    }
  }, [onRemoved, options]);

  const clearRootError = useCallback(() => setRootError(null), []);

  return useMemo(
    () => ({
      provider,
      setProvider,
      apiKey,
      setApiKey,
      model,
      setModel,
      errors,
      rootError,
      isSubmitting,
      isRemoving,
      hasKey: keyStored,
      onSubmit,
      handleRemove,
      clearRootError,
    }),
    [
      apiKey,
      clearRootError,
      errors,
      handleRemove,
      isRemoving,
      isSubmitting,
      keyStored,
      model,
      onSubmit,
      provider,
      rootError,
    ],
  );
}

export default useAiCredentialsForm;
