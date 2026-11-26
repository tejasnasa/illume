/**
 * Invoke a server action that finishes with `redirect()`.
 * @module redirectingAction
 */
import { unstable_rethrow } from "next/navigation";

/**
 * Runs a server action that finishes by redirecting to the dashboard.
 *
 * A successful run ends in `redirect()`, which reaches the client as a thrown
 * framework error rather than a result -- `unstable_rethrow` hands it back to
 * the router so it navigates, and this returns `null` either way. Only a
 * genuine failure yields a message, which the caller renders next to the
 * button that triggered it.
 *
 * @param run - The action to invoke.
 * @param fallbackMessage - Shown when the failure carries no usable message,
 *                          which is the norm once React masks server errors in
 *                          production.
 * @returns The failure message, or null when the action redirected.
 */
export async function runRedirectingAction(
  run: () => Promise<unknown>,
  fallbackMessage: string,
): Promise<string | null> {
  try {
    await run();
    return null;
  } catch (err) {
    try {
      unstable_rethrow(err);
    } catch {
      return null;
    }
    return err instanceof Error ? err.message : fallbackMessage;
  }
}
