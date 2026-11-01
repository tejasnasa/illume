/**
 * Contact form state with validation and submission.
 *
 * @module UseContactForm
 *
 * Port of ``client/src/hooks/useContactForm.ts``. The web version drives
 * ``react-hook-form`` with a zod resolver; the mobile app keeps the same
 * contract -- validate, submit, surface the failure -- with a hand-rolled
 * state machine over the same zod schema the app already ships
 * (``src/types/validators.ts``).
 *
 * Two details carried over from the web:
 *
 * - A single banner error rather than one per field. The form is short
 *   enough that a reader does not want to hunt for which box is red.
 * - The honeypot travels with the payload. Dropping it would leave the
 *   server checking a field the client never sent.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { submitContact, type SettingsRequestOptions } from "@/api/settings";
import { ApiError } from "@/lib/apiError";
import { contactSchema } from "@/types/validators";

/**
 * Args for {@link useContactForm}.
 */
export interface UseContactFormArgs {
  /**
   * Name to prefill.
   *
   * It comes from the visitor's own session and is a convenience only --
   * it is resubmitted as an ordinary form value, so it is no more
   * trustworthy than anything typed by hand.
   */
  name?: string;
  /** Email to prefill, from the visitor's own session. */
  email?: string;
  /** Transport overrides, so a test can inject a backend and a fetch. */
  options?: SettingsRequestOptions;
}

/**
 * State and actions returned by {@link useContactForm}.
 */
export interface UseContactFormResult {
  /** The chosen category slug. Empty until the reader picks one. */
  category: string;
  /** Choose a category. */
  setCategory: (value: string) => void;
  /** The name in the form. */
  name: string;
  /** Set the name. */
  setName: (value: string) => void;
  /** The email in the form. */
  email: string;
  /** Set the email. */
  setEmail: (value: string) => void;
  /** The message in the form. */
  message: string;
  /** Set the message. */
  setMessage: (value: string) => void;
  /** The failure message from the last attempt, if any. */
  error: string | null;
  /** The confirmation shown after a successful submission. */
  successMessage: string | null;
  /** True while a submission is in flight. */
  isSubmitting: boolean;
  /** Validate and send the form. */
  onSubmit: () => Promise<boolean>;
  /** Dismiss the current failure. */
  clearError: () => void;
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
 * Manage the contact form.
 *
 * @param args - Prefilled identity and transport overrides.
 * @returns The field values, the banner error and the submit handler.
 */
export function useContactForm({
  name: initialName = "",
  email: initialEmail = "",
  options,
}: UseContactFormArgs = {}): UseContactFormResult {
  // The category starts empty on purpose: an untouched category must fail
  // validation rather than silently defaulting to a value the reader never
  // chose.
  const [category, setCategory] = useState("");
  const [name, setName] = useState(initialName);
  const [email, setEmail] = useState(initialEmail);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // The profile arrives after the screen mounts (``/auth/me`` is an async
  // cold-start read, and may be retried). Adopting it when it lands fills
  // the identity fields, but only while the reader has not typed over them.
  const lastDefaults = useRef({ name: initialName, email: initialEmail });
  useEffect(() => {
    if (
      lastDefaults.current.name === initialName &&
      lastDefaults.current.email === initialEmail
    ) {
      return;
    }
    const previous = lastDefaults.current;
    lastDefaults.current = { name: initialName, email: initialEmail };
    setName((current) => (current === previous.name ? initialName : current));
    setEmail((current) => (current === previous.email ? initialEmail : current));
  }, [initialName, initialEmail]);

  const onSubmit = useCallback(async (): Promise<boolean> => {
    setError(null);
    setSuccessMessage(null);

    const result = contactSchema.safeParse({
      category,
      name,
      email,
      message,
      // No honeypot field is rendered on a phone, so the value is always
      // empty. It still travels so the server sees the field it checks.
      illume_hp: "",
    });

    if (!result.success) {
      const issue = result.error.issues[0];
      setError(issue?.message ?? "Please check the form and try again.");
      return false;
    }

    setIsSubmitting(true);
    try {
      await submitContact(
        {
          category: result.data.category,
          name: result.data.name,
          email: result.data.email,
          message: result.data.message,
          illume_hp: result.data.illume_hp,
        },
        options,
      );

      setSuccessMessage("Thanks for getting in touch. We'll reply by email.");
      // Clear the body but keep the identity, so a second message does not
      // mean retyping it.
      setMessage("");
      return true;
    } catch (cause) {
      setError(messageOf(cause, "Something went wrong. Please try again."));
      return false;
    } finally {
      setIsSubmitting(false);
    }
  }, [category, email, message, name, options]);

  const clearError = useCallback(() => setError(null), []);

  return {
    category,
    setCategory,
    name,
    setName,
    email,
    setEmail,
    message,
    setMessage,
    error,
    successMessage,
    isSubmitting,
    onSubmit,
    clearError,
  };
}

export default useContactForm;
