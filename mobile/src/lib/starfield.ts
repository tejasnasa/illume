/**
 * The star positions behind every screen.
 *
 * A seeded generator, so the field looks the same on every launch. Positions
 * are fractions of the screen so the same field fits any size; the component
 * snaps them to a coarse grid.
 */

/** One star: a position as a fraction of the screen, and a brightness. */
export interface Star {
  /** Horizontal position, 0 to 1. */
  x: number;
  /** Vertical position, 0 to 1. */
  y: number;
  /** Brightness, 0 to 1. */
  b: number;
}

/** Side of one pixel-art cell, in density-independent pixels. */
export const STAR_CELL = 4;
/** One star per this many cells. */
export const STAR_DENSITY = 150;

/**
 * A small seeded generator returning numbers in [0, 1).
 *
 * @param seed - Any integer.
 * @returns The generator.
 */
export function mulberry(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Builds the star field for a screen size.
 *
 * @param width - Screen width in density-independent pixels.
 * @param height - Screen height in density-independent pixels.
 * @returns Stars snapped to the cell grid; empty for a zero-sized screen.
 */
export function buildStars(width: number, height: number): Star[] {
  const cols = Math.ceil(width / STAR_CELL);
  const rows = Math.ceil(height / STAR_CELL);
  if (cols <= 0 || rows <= 0) return [];
  const rnd = mulberry(41);
  const count = Math.round((cols * rows) / STAR_DENSITY);
  return Array.from({ length: count }, () => ({
    x: Math.floor(rnd() * cols) / cols,
    y: Math.floor(rnd() * rows) / rows,
    b: rnd(),
  }));
}
