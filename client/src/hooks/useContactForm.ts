/**
 * Contact form state with validation and submission.
 * @module UseContactForm
 */

import apiError from "@/lib/apiError";
import { toast } from "@/lib/use-toast";
import { contactSchema } from "@/types/validators";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

/** The category slugs the form accepts, as the schema declares them. */
type Category = z.infer<typeof contactSchema>["category"];

/** Prefilled identity for a signed-in visitor. */
type Defaults = {
  name?: string;
  email?: string;
};

/**
 * Manages the contact form: validation, submission, and success feedback.
 *
 * @param defaults - Name and email to prefill. These come from the visitor's own session
 *   and are a convenience only -- they are resubmitted as ordinary form values, so they
 *   are no more trustworthy than anything typed by hand.
 * @returns Register function, first error, submitting flag, and submit handler.
 */
export default function useContactForm(defaults?: Defaults) {
  const form = useForm<z.infer<typeof contactSchema>>({
    resolver: zodResolver(contactSchema),
    // `category` is absent so the select starts on its disabled placeholder, which makes
    // an untouched category fail validation rather than silently defaulting to a value
    // the visitor never chose.
    defaultValues: {
      name: defaults?.name ?? "",
      email: defaults?.email ?? "",
      message: "",
      illume_hp: "",
    },
  });

  // Surface a single banner error instead of one per field.
  const { category, name, email, message, root } = form.formState.errors;
  const firstError =
    category?.message ||
    name?.message ||
    email?.message ||
    message?.message ||
    root?.message;

  const onSubmit = form.handleSubmit(async (data) => {
    try {
      // The whole `data` object goes over the wire, honeypot included. Dropping
      // `illume_hp` here would leave the field looking present in the markup while
      // never reaching the server that checks it.
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/contact`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          // Carries the session cookie when there is one, which is how a submission
          // from a signed-in visitor gets attributed to their account.
          credentials: "include",
          body: JSON.stringify(data),
        },
      );

      if (!res.ok) {
        throw await apiError(res, "Something went wrong. Please try again.");
      }

      toast({
        title: "Message sent",
        description: "Thanks for getting in touch. We'll reply by email.",
        variant: "success",
      });

      // Clear the body but keep their identity filled in, so a second message does not
      // mean retyping it.
      form.reset({ ...form.getValues(), message: "", illume_hp: "" });
    } catch (error) {
      // Backend message lands in root so the banner shows it (not a field).
      form.setError("root", {
        message:
          (error as { message?: string }).message ??
          "Something went wrong. Please try again.",
      });
    }
  });

  return {
    register: form.register,
    setCategory: (value: string) =>
      form.setValue("category", value as Category, { shouldValidate: true }),
    category: (form.watch("category") as string | undefined) ?? "",
    firstError,
    isSubmitting: form.formState.isSubmitting,
    onSubmit,
  };
}
