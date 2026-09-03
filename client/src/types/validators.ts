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
  email: z.email({ message: "Enter a valid email." }).trim(),
  password: z
    .string()
    .min(8, { message: "Password must be at least 8 characters long" })
    // Letter + number + symbol required so weak passwords fail fast client-side.
    .regex(/[a-zA-Z]/, {
      message: "Password must contain at least one letter.",
    })
    .regex(/[0-9]/, { message: "Password must contain at least one number." })
    .regex(/[^a-zA-Z0-9]/, {
      message: "Password must contain at least one special character.",
    })
    .trim(),
});

/**
 * Login form validation: email plus minimum-length password.
 */
export const loginSchema = z.object({
  email: z.email({ message: "Enter a valid email." }).trim(),
  password: z.string().min(8, { message: "Enter a valid password" }).trim(),
});

/**
 * Repository creation validation: must be a github.com owner/repo URL.
 */
export const repoCreateSchema = z.object({
  github_url: z
    .url({ message: "Enter a valid GitHub repository URL." })
    .trim()
    // z.url() alone allows any URL, so narrow to github.com owner/repo paths.
    .refine((url) => /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/.test(url), {
      message: "URL must point to a valid GitHub repository.",
    }),
});
