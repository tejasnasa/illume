/**
 * Form state, validation, and submit lifecycle for the BYOK credentials editor.
 * @module UseAiCredentialsForm
 */

import removeAiCredentialsAction from "@/actions/removeAiCredentials";
import saveAiCredentialsAction from "@/actions/saveAiCredentials";
import { toast } from "@/lib/use-toast";
import { aiCredentialsSchema } from "@/types/validators";
import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

/**
 * The shape of one row from the provider preset table on the client. Mirrors
 * `PROVIDER_PRESETS` in `components/AiSettings.tsx`; the form only cares about
 * the key when seeding the `provider` field.
 */
export type AiProviderPreset = {
  key: string;
  label: string;
  defaultModel: string;
};

/**
 * Args for {@link useAiCredentialsForm}.
 */
export type UseAiCredentialsFormArgs = {
  /** Presets used to resolve a sensible default model when the user leaves the field blank. */
  presets: AiProviderPreset[];
  /** Initial provider key (the saved row, or undefined for a fresh user). */
  initialProviderKey: string | undefined;
  /** Initial model id (the saved row, or undefined). */
  initialModel: string | undefined;
};

/**
 * Wires the BYOK form to react-hook-form with zod validation, and threads
 * the saved / removed callbacks back through the existing server actions.
 *
 * The provider field drives the model placeholder locally, so the component
 * reads it via `watch()`. The remove flow stays a separate button so its
 * pending state is independent of the save button.
 *
 * @param args - Seed values for the form (saved provider / model) and the
 *               preset table used for placeholder resolution.
 * @returns RHF helpers, submit/remove handlers, and the busy flags the
 *          buttons need.
 */
export default function useAiCredentialsForm({
  presets,
  initialProviderKey,
  initialModel,
}: UseAiCredentialsFormArgs) {
  const router = useRouter();
  const [isRemoving, setIsRemoving] = useState(false);

  const form = useForm<z.infer<typeof aiCredentialsSchema>>({
    resolver: zodResolver(aiCredentialsSchema),
    defaultValues: {
      provider: initialProviderKey ?? presets[0]?.key ?? "",
      apiKey: "",
      model: initialModel ?? "",
    },
  });

  const onSubmit = form.handleSubmit(async (data) => {
    try {
      // Fall back to the active preset's default when the user left the field blank;
      // zod ensures this is a non-empty string by the time we reach here.
      const preset = presets.find((p) => p.key === data.provider);
      const model = data.model.trim() || preset?.defaultModel || "";

      await saveAiCredentialsAction({
        provider: data.provider,
        apiKey: data.apiKey,
        model,
      });

      // The backend probes the key before storing, so a successful return is a
      // validated credential. Clear the key field -- the server never echoes it
      // back, and we never want to sit on it in component state across renders.
      form.resetField("apiKey");
      toast({
        title: "AI credentials saved",
        description: `Key validated against ${preset?.label ?? "your provider"}. Future analyses will use your provider.`,
        variant: "success",
      });
      router.refresh();
    } catch (error) {
      // Backend message lands in root so the banner shows it (not a field).
      form.setError("root", {
        message:
          (error as { message?: string }).message ??
          "Failed to save AI credentials.",
      });
    }
  });

  /**
   * Calls the remove action and refreshes the route so the layout picks up
   * the cleared credential state.
   */
  const handleRemove = async () => {
    form.clearErrors("root");
    setIsRemoving(true);
    try {
      await removeAiCredentialsAction();
      toast({
        title: "AI credentials removed",
        description:
          "Your existing analyses are preserved. Future ingests will require a new key.",
        variant: "success",
      });
      router.refresh();
    } catch (error) {
      form.setError("root", {
        message:
          (error as { message?: string }).message ??
          "Failed to remove AI credentials.",
      });
    } finally {
      setIsRemoving(false);
    }
  };

  return {
    register: form.register,
    watch: form.watch,
    setValue: form.setValue,
    errors: form.formState.errors,
    rootError: form.formState.errors.root?.message,
    isSubmitting: form.formState.isSubmitting,
    isRemoving,
    onSubmit,
    handleRemove,
  };
}
