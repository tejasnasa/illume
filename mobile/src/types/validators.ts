/**
 * Zod validation schemas for auth and repository forms.
 * @module Validators
 */

import { z } from "zod";

/**
 * Signup form validation: name, email, and a hardened password policy.
 */
export const signupSchema = z.object({
  name: z
    .string()
    .min(2, { message: "Full name must be at least 2 characters long." }),
  email: z
    .string()
    .trim()
    .pipe(z.email({ message: "Enter a valid email." })),
  password: z
    .string()
    .trim()
    .min(8, { message: "Password must be at least 8 characters long" })
    // Letter + number + symbol required so weak passwords fail fast client-side.
    .regex(/[a-zA-Z]/, {
      message: "Password must contain at least one letter.",
    })
    .regex(/[0-9]/, { message: "Password must contain at least one number." })
    .regex(/[^a-zA-Z0-9]/, {
      message: "Password must contain at least one special character.",
    }),
});

/**
 * Login form validation: email plus minimum-length password.
 */
export const loginSchema = z.object({
  email: z
    .string()
    .trim()
    .pipe(z.email({ message: "Enter a valid email." })),
  password: z.string().trim().min(8, { message: "Enter a valid password" }),
});

/**
 * Repository creation validation: must be a github.com owner/repo URL.
 */
export const repoCreateSchema = z.object({
  github_url: z
    .string()
    .trim()
    .pipe(z.url({ message: "Enter a valid GitHub repository URL." }))
    // z.url() alone allows any URL, so narrow to github.com owner/repo paths.
    .refine((url) => /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/.test(url), {
      message: "URL must point to a valid GitHub repository.",
    }),
});

/**
 * BYOK credentials form validation.
 */
export const aiCredentialsSchema = z.object({
  provider: z.string().min(1, { message: "Pick a provider." }),
  apiKey: z
    .string()
    .trim()
    .min(8, { message: "API key must be at least 8 characters." })
    .max(512, { message: "API key must be at most 512 characters." }),
  model: z
    .string()
    .trim()
    .max(128, { message: "Model id must be at most 128 characters." }),
});

/**
 * The categories a contact submission can be filed under, in display order.
 *
 * The values are the server's `ContactCategory` slugs; the labels are what the operator
 * sees in the email subject, so they are kept in step with it deliberately.
 */
export const contactCategories = [
  { value: "bug", label: "Bug report" },
  { value: "feature", label: "Feature request" },
  { value: "question", label: "Question" },
  { value: "other", label: "Other" },
] as const;

/**
 * Contact form validation.
 *
 * The length bounds mirror the server's, so a submission that is too long or too short is
 * rejected here rather than travelling to the API to earn a 422.
 *
 * `illume_hp` is the honeypot: a decoy field no visitor can see, which automated
 * submitters fill because they post every input they parse. It is left unconstrained on
 * purpose -- rejecting it here would both tell a bot which field caught it and lock out a
 * real visitor whose browser autofilled it. The decision belongs on the server, which
 * discards the submission and answers exactly as though it had been delivered.
 */
export const contactSchema = z.object({
  category: z.enum(
    contactCategories.map((c) => c.value),
    { message: "Pick a category." },
  ),
  name: z
    .string()
    .trim()
    .min(2, { message: "Name must be at least 2 characters long." })
    .max(100, { message: "Name must be at most 100 characters long." }),
  email: z
    .string()
    .trim()
    .pipe(z.email({ message: "Enter a valid email." })),
  message: z
    .string()
    .trim()
    .min(10, { message: "Message must be at least 10 characters long." })
    .max(5000, { message: "Message must be at most 5000 characters long." }),
  illume_hp: z.string(),
});

