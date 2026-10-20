/**
 * Repository creation form state with ingestion kick-off.
 *
 * @module UseRepoForm
 *
 * Port of ``client/src/hooks/useRepoForm.ts``. The web version drives
 * ``react-hook-form``; that library is DOM-oriented and has no place in a
 * React Native bundle, so the mobile version keeps the same contract --
 * validate, submit, surface the failure -- with a hand-rolled state
 * machine.
 *
 * **The hook does not navigate.** The web hook ends with a
 * ``router.push``, but the mobile picker is a *modal route*, and pushing
 * a new screen on top of it would leave the picker in the stack: the
 * back button would return to the picker rather than to the dashboard.
 * The caller decides what happens after a creation instead -- the
 * picker reports the result, and the route (which knows it is a modal)
 * replaces itself with the new repository's page.
 *
 * The free-tier gate is the interesting part. The backend answers a
 * creation request from a keyless user who has spent their allowance with
 * **402**, and the message it sends is the copy the user should read. The
 * hook distinguishes that case from an ordinary failure so the screen can
 * point at Settings instead of showing a generic "something went wrong".
 */

import { useCallback, useState } from "react";

import {
  createRepository,
  type CreateRepositoryResponse,
} from "@/api/repository";
import { ApiError } from "@/lib/apiError";

/** The version of a repository to ingest. */
export interface RepoFormValues {
  /** The GitHub URL of the repository to ingest. */
  github_url: string;
  /** Branch to ingest; ``null`` means the repository's default. */
  branch: string | null;
  /** Commit SHA to pin the ingest to; ``null`` means the branch tip. */
  commit_sha: string | null;
}

/** State and actions returned by :func:`useRepoForm`. */
export interface UseRepoFormResult {
  /**
   * Submit the creation request.
   *
   * @param values - The repository and version to ingest.
   * @returns The created repository, or ``null`` when the request failed.
   */
  submit: (values: RepoFormValues) => Promise<CreateRepositoryResponse | null>;
  /** True while the creation request is in flight. */
  isSubmitting: boolean;
  /** The failure message from the last attempt, if any. */
  ingestError: string | null;
  /** True when the last failure was a spent free-tier allowance. */
  quotaExceeded: boolean;
  /** Dismiss the current error. */
  clearError: () => void;
}

/**
 * Manages the new-repository submission.
 *
 * @returns The submit function plus the error and loading state.
 */
export function useRepoForm(): UseRepoFormResult {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [ingestError, setIngestError] = useState<string | null>(null);
  const [quotaExceeded, setQuotaExceeded] = useState(false);

  const clearError = useCallback(() => {
    setIngestError(null);
    setQuotaExceeded(false);
  }, []);

  const submit = useCallback(
    async (
      values: RepoFormValues,
    ): Promise<CreateRepositoryResponse | null> => {
      setIsSubmitting(true);
      setIngestError(null);
      setQuotaExceeded(false);

      try {
        return await createRepository({
          github_url: values.github_url,
          branch: values.branch,
          commit_sha: values.commit_sha,
        });
      } catch (error) {
        if (error instanceof ApiError) {
          setIngestError(error.message || "Failed to start ingestion process");
          setQuotaExceeded(error.kind === "quota");
        } else {
          setIngestError("Failed to start ingestion process");
        }
        return null;
      } finally {
        setIsSubmitting(false);
      }
    },
    [],
  );

  return { submit, isSubmitting, ingestError, quotaExceeded, clearError };
}

export default useRepoForm;
