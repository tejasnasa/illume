/**
 * Sizing and geometry for the selection and search brackets.
 *
 * @module graphBrackets
 *
 * A bracket is four corner marks drawn around a node. It is built from line
 * segments rather than a texture: the renderer runs over `expo-gl`, where
 * there is no DOM canvas to paint a sprite texture on, and a texture built
 * without one would be a data array that has to be kept in step with the
 * colour. Line segments need neither.
 *
 * Like the web client, a bracket is never drawn smaller than a fixed number
 * of screen pixels, so zooming out leaves it readable, while zooming in
 * still lets it grow to frame a large node.
 */

/** The smallest a bracket is drawn, in screen pixels. */
export const BRACKET_MIN_PX = 28;

/** How far each corner arm reaches along a side, as a fraction of it. */
export const BRACKET_ARM = 0.38;

/** The camera's vertical field of view, in degrees. */
export const CAMERA_FOV_DEG = 50;

/**
 * World units covered by one screen pixel at a distance from the camera.
 *
 * @param distance - Distance from the camera to the point.
 * @param viewportHeight - Height of the drawing surface in pixels.
 * @param fovDeg - Vertical field of view in degrees.
 * @returns World units per pixel; 0 when the inputs cannot give one.
 */
export function worldPerPixel(
  distance: number,
  viewportHeight: number,
  fovDeg = CAMERA_FOV_DEG,
): number {
  if (!(distance > 0) || !(viewportHeight > 0)) return 0;
  return (2 * distance * Math.tan((fovDeg * Math.PI) / 360)) / viewportHeight;
}

/**
 * The half-side of a bracket in world units.
 *
 * It is the larger of the node's own framing size and `minPx` pixels' worth
 * of world units at the node's distance.
 *
 * @param base - The half-side that frames the node in world units.
 * @param distance - Distance from the camera to the node.
 * @param viewportHeight - Height of the drawing surface in pixels.
 * @param minPx - The on-screen floor for the full side, in pixels.
 * @param fovDeg - Vertical field of view in degrees.
 * @returns A finite, non-negative half-side.
 */
export function bracketHalfSize(
  base: number,
  distance: number,
  viewportHeight: number,
  minPx = BRACKET_MIN_PX,
  fovDeg = CAMERA_FOV_DEG,
): number {
  const safeBase = Number.isFinite(base) && base > 0 ? base : 0;
  const floor = (minPx / 2) * worldPerPixel(distance, viewportHeight, fovDeg);
  return Math.max(safeBase, Number.isFinite(floor) ? floor : 0);
}

/**
 * Line-segment vertices of a unit bracket: four corners, two arms each.
 *
 * The bracket lies in the XY plane with half-side 1, centred on the origin.
 *
 * @param arm - How far each arm reaches, as a fraction of a full side.
 * @returns `xyz` triples, two per segment, eight segments.
 */
export function bracketVertices(arm = BRACKET_ARM): Float32Array {
  const reach = 1 - 2 * arm;
  const out: number[] = [];
  for (const sx of [-1, 1]) {
    for (const sy of [-1, 1]) {
      // Horizontal arm, then vertical arm, both leaving the corner inward.
      out.push(sx, sy, 0, sx * reach, sy, 0);
      out.push(sx, sy, 0, sx, sy * reach, 0);
    }
  }
  return new Float32Array(out);
}
