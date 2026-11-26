/**
 * Contact form panel: category, identity, and message, then a sent state.
 * @module ContactForm
 */
"use client";

import useContactForm from "@/hooks/useContactForm";
import { contactCategories } from "@/types/validators";
import { useEffect, useRef } from "react";
import Button from "./ui/Button";
import Input from "./ui/Input";
import Textarea from "./ui/Textarea";

/** Small uppercase field label. */
const FIELD_LABEL =
  "font-pixel text-[11px] tracking-[0.12em] text-(--muted-foreground) uppercase";

type Category = (typeof contactCategories)[number]["value"];

/** What each category card says, and the hint its message box shows. */
const CATEGORY_COPY: Record<Category, { title: string; blurb: string; hint: string }> = {
  bug: {
    title: "Bug report",
    blurb: "Something broke or looks wrong",
    hint: "What happened, what you expected, and how to reproduce it.",
  },
  feature: {
    title: "Feature idea",
    blurb: "Something Illume should do",
    hint: "What you would like, and the problem it would solve for you.",
  },
  question: {
    title: "Question",
    blurb: "How something works",
    hint: "Ask away. Mention the repository if it is about one.",
  },
  other: {
    title: "Something else",
    blurb: "Feedback, hello, anything",
    hint: "Whatever is on your mind.",
  },
};

type Props = {
  /** Name to prefill, when the visitor is signed in. */
  defaultName?: string;
  /** Email to prefill, when the visitor is signed in. */
  defaultEmail?: string;
};

/**
 * Renders the contact form, and once a message goes through, a sent panel in
 * its place with a way back to write another.
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
    dismissSuccess,
    isSubmitting,
    onSubmit,
  } = useContactForm({
    name: defaultName,
    email: defaultEmail,
  });
  const sentRef = useRef<HTMLHeadingElement>(null);

  // The form the visitor was in has gone, so focus moves to what replaced it.
  useEffect(() => {
    if (successMessage) sentRef.current?.focus();
  }, [successMessage]);

  if (successMessage) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="rise flex w-full max-w-130 flex-col items-start gap-4"
      >
        <span className="font-pixel text-xs tracking-[0.12em] text-(--success) uppercase">
          ✓ Message sent
        </span>
        <h2
          ref={sentRef}
          tabIndex={-1}
          className="m-0 font-pixel text-[clamp(1.8rem,3vw,2.6rem)] leading-tight font-normal tracking-[-0.01em] outline-none"
        >
          Thanks, it is on its way.
        </h2>
        <p className="m-0 max-w-110 text-[15px] leading-relaxed text-zinc-400">
          A reply will land in your inbox. If it is a bug, a link to the
          repository or a screenshot helps a lot.
        </p>
        <button
          type="button"
          onClick={dismissSuccess}
          className="ghost rounded-sm border border-(--input) px-4 py-2.75 font-pixel text-[13px] tracking-[0.06em] text-zinc-300 uppercase hover:cursor-pointer"
        >
          Send another
        </button>
      </div>
    );
  }

  const hint = CATEGORY_COPY[category as Category]?.hint ?? CATEGORY_COPY.bug.hint;

  return (
    <form
      className="flex w-full max-w-130 flex-col gap-5.5"
      onSubmit={onSubmit}
      noValidate
    >
      <fieldset className="m-0 flex flex-col gap-2.5 border-0 p-0">
        <legend className={`${FIELD_LABEL} mb-2.5 p-0`}>What is this about?</legend>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {contactCategories.map(({ value }) => {
            const copy = CATEGORY_COPY[value];
            return (
              <label
                key={value}
                className="flex cursor-pointer flex-col gap-1 rounded-sm border border-white/10 bg-(--card) px-3.5 py-3 transition-colors duration-150 ease-[steps(2)] hover:border-white/25 has-checked:border-(--accent) has-checked:bg-(--accent)/6 has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-(--accent)"
              >
                <input
                  type="radio"
                  name="category"
                  value={value}
                  checked={category === value}
                  onChange={() => setCategory(value)}
                  className="sr-only"
                />
                <span className="font-pixel text-[13px] tracking-[0.08em] text-(--foreground) uppercase">
                  {copy.title}
                </span>
                <span className="text-[13px] text-(--muted-foreground)">{copy.blurb}</span>
              </label>
            );
          })}
        </div>
      </fieldset>

      <div className="grid gap-3.5 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <label htmlFor="name" className={FIELD_LABEL}>
            Name
          </label>
          <Input
            id="name"
            type="text"
            autoComplete="name"
            placeholder="Tejas Nasa"
            {...register("name")}
          />
        </div>

        <div className="flex flex-col gap-2">
          <label htmlFor="email" className={FIELD_LABEL}>
            Email
          </label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            {...register("email")}
          />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="message" className={FIELD_LABEL}>
          Message
        </label>
        <Textarea id="message" size="lg" placeholder={hint} {...register("message")} />
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
        <p role="alert" className="m-0 text-sm text-(--destructive)">
          {firstError}
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="font-pixel text-[11px] tracking-[0.1em] text-(--faint-foreground) uppercase">
          Usually a reply within two days
        </span>
        <Button size="md" loading={isSubmitting}>
          Send message <span aria-hidden="true">↵</span>
        </Button>
      </div>
    </form>
  );
}
