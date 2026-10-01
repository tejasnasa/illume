/**
 * Contact form panel: category, identity, and message.
 * @module ContactForm
 */
"use client";

import useContactForm from "@/hooks/useContactForm";
import { contactCategories } from "@/types/validators";
import Button from "./ui/Button";
import Input from "./ui/Input";
import Select from "./ui/Select";
import Textarea from "./ui/Textarea";

type Props = {
  /** Name to prefill, when the visitor is signed in. */
  defaultName?: string;
  /** Email to prefill, when the visitor is signed in. */
  defaultEmail?: string;
};

/**
 * Renders the contact form with a single error banner and an inline success notice.
 *
 * @param defaultName - Name from the visitor's session, if any.
 * @param defaultEmail - Email from the visitor's session, if any.
 * @returns The form panel.
 */
export default function ContactForm({ defaultName, defaultEmail }: Props) {
  const {
    register,
    setCategory,
    category,
    firstError,
    successMessage,
    isSubmitting,
    onSubmit,
  } = useContactForm({
    name: defaultName,
    email: defaultEmail,
  });

  return (
    <form
      className="glass-card rounded-sm p-8 sm:p-10 w-full max-w-2xl flex flex-col gap-5"
      onSubmit={onSubmit}
      noValidate
    >
      <Select
        id="category"
        label="What is this about?"
        value={category}
        onChange={setCategory}
        options={contactCategories}
        placeholder="Select a category"
      />

      <div className="grid sm:grid-cols-2 gap-5">
        <div className="flex flex-col gap-1">
          <label htmlFor="name" className="text-sm">
            Name
          </label>
          <Input
            id="name"
            type="text"
            placeholder="Tejas Nasa"
            {...register("name")}
          />
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="email" className="text-sm">
            Email
          </label>
          <Input
            id="email"
            type="email"
            placeholder="you@example.com"
            {...register("email")}
          />
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="message" className="text-sm">
          Message
        </label>
        <Textarea
          id="message"
          size="lg"
          placeholder="What happened, what you expected, and how to reproduce it."
          {...register("message")}
        />
      </div>

      {/*
        Decoy field. A visitor cannot see it, tab to it, or be told it exists; an automated
        submitter fills it because it posts every input it parses. Off-screen rather than
        `display: none`, which is a known trick that better bots skip. The name is
        deliberately meaningless because password managers autofill fields called
        "website" or "company", and a false positive here would discard a real message.
      */}
      <div
        className="absolute left-[-9999px] top-auto h-px w-px overflow-hidden"
        aria-hidden="true"
      >
        <label htmlFor="illume_hp">Leave this field empty</label>
        <Input
          id="illume_hp"
          type="text"
          tabIndex={-1}
          autoComplete="off"
          {...register("illume_hp")}
        />
      </div>

      {firstError && (
        <p className="text-(--destructive) text-sm">{firstError}</p>
      )}
      {successMessage && (
        <p
          className="text-(--chart-1) text-sm"
          role="status"
          aria-live="polite"
        >
          {successMessage}
        </p>
      )}

      <Button className="w-full" size="md" loading={isSubmitting}>
        Send message
      </Button>
    </form>
  );
}
