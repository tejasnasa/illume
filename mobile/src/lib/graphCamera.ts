/**
 * Shared orbit-camera mathematics.
 *
 * @module graphCamera
 *
 * Kept pure and free of any renderer or React Native import so it can be
 * unit tested off-device. The camera orbits a target point, which is the
 * origin until the reader focuses a node and the origin of the graph
 * afterwards.
 *
 * The projection here is the hand-rolled inverse of the view transform the
 * renderer applies. The renderer picks nodes with three's own projection --
 * which is exact by construction -- but the shape of the orbit is the same,
 * so the two agree on where a node is.
 */

/** Camera placement in spherical coordinates about the target. */
export interface OrbitCamera {
  /** Rotation about the vertical axis, in radians. */
  theta: number;
  /** Elevation, in radians. */
  phi: number;
  /** Distance from the target. */
  radius: number;
}

/** Where a world point lands on screen. */
export interface ProjectedPoint {
  x: number;
  y: number;
  /** Distance in front of the camera. Negative means the point is behind it. */
  depth: number;
  /** Perspective scale factor at this depth; 0 when behind the camera. */
  scale: number;
}

/** Default time for one full revolution, in milliseconds. */
export const ORBIT_PERIOD_MS = 24_000;

/** Elevation held constant during auto-orbit. Roughly 35 degrees above the equator. */
const ORBIT_PHI = (35 * Math.PI) / 180;

/** The lowest the camera may drop below the target. */
export const MIN_PHI = (5 * Math.PI) / 180;

/** The highest the camera may rise above the target. */
export const MAX_PHI = (170 * Math.PI) / 180;

/**
 * Where the camera is at a moment in time.
 *
 * @param elapsedMs - Milliseconds since the orbit began.
 * @param boundingRadius - Radius containing the graph.
 * @param periodMs - Duration of one full revolution.
 * @returns The camera placement.
 */
export function orbitAt(
  elapsedMs: number,
  boundingRadius: number,
  periodMs = ORBIT_PERIOD_MS,
): OrbitCamera {
  return {
    theta: ((elapsedMs % periodMs) / periodMs) * Math.PI * 2,
    phi: ORBIT_PHI,
    // 2.4x the bounding radius frames the graph with a little margin.
    radius: boundingRadius * 2.4,
  };
}

/**
 * Clamp an elevation to the range the camera may travel.
 *
 * @param phi - The elevation in radians.
 * @returns The clamped elevation.
 */
export function clampPhi(phi: number): number {
  return Math.min(MAX_PHI, Math.max(MIN_PHI, phi));
}

/**
 * Project a world point through an orbit camera onto a viewport.
 *
 * Implemented as two rotations followed by a perspective divide rather than
 * a full view matrix: the camera always looks at its target, so the general
 * case buys nothing.
 *
 * @param x - World x.
 * @param y - World y.
 * @param z - World z.
 * @param camera - Camera placement.
 * @param width - Viewport width in pixels.
 * @param height - Viewport height in pixels.
 * @param target - The point the camera looks at.
 * @returns Screen position, depth, and perspective scale.
 */
export function projectPoint(
  x: number,
  y: number,
  z: number,
  camera: OrbitCamera,
  width: number,
  height: number,
  target: readonly [number, number, number] = [0, 0, 0],
): ProjectedPoint {
  const dx = x - target[0];
  const dy = y - target[1];
  const dz = z - target[2];

  const cosT = Math.cos(camera.theta);
  const sinT = Math.sin(camera.theta);
  const cosP = Math.cos(camera.phi);
  const sinP = Math.sin(camera.phi);

  // Rotate about Y.
  const x1 = dx * cosT - dz * sinT;
  const z1 = dx * sinT + dz * cosT;

  // Rotate about X.
  const y2 = dy * cosP - z1 * sinP;
  const z2 = dy * sinP + z1 * cosP;

  // Push the camera back along +Z.
  const depth = z2 + camera.radius;

  // The viewport's smaller dimension sets the focal length, so a portrait
  // phone and a landscape tablet frame the graph the same way.
  const focal = Math.min(width, height) * 0.9;
  const scale = depth > 0.01 ? focal / depth : 0;

  return {
    x: width / 2 + x1 * scale,
    y: height / 2 - y2 * scale,
    depth,
    scale,
  };
}
