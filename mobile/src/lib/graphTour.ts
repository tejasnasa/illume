/**
 * Stepping rules for the reading-order tour.
 *
 * @module graphTour
 */

/** How long the tour lingers on each file while playing, in milliseconds. */
export const TOUR_STEP_MS = 4000;

/**
 * The step a playing tour moves to next.
 *
 * @param current - The step now showing, or null before the tour has started.
 * @param total - How many steps the tour has.
 * @returns The next index, or null when the tour has reached its end or has
 *   no steps.
 */
export function nextTourIndex(current: number | null, total: number): number | null {
  if (!(total > 0)) return null;
  const next = current === null ? 0 : current + 1;
  return next >= total ? null : next;
}
