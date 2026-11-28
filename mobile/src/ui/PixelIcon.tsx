/**
 * Small pixel-art icons, drawn as grids of squares.
 *
 * @module PixelIcon
 *
 * Every icon is a set of integer-aligned rectangles on a 12 by 12 grid,
 * rendered with crisp edges so it stays sharp at any size. They share the
 * look of the pixel font used for labels.
 */

import Svg, { Rect } from "react-native-svg";

/** The icons available. */
export type PixelIconName =
  | "overview"
  | "graph"
  | "files"
  | "terms"
  | "gear"
  | "back";

/** One rectangle as ``[x, y, width, height]``. */
type Box = readonly [number, number, number, number];

const ICONS: Record<PixelIconName, readonly Box[]> = {
  overview: [
    [0, 0, 5, 5],
    [7, 0, 5, 5],
    [0, 7, 5, 5],
    [7, 7, 5, 5],
  ],
  graph: [
    [4, 0, 4, 4],
    [5, 4, 2, 2],
    [2, 6, 8, 2],
    [0, 8, 4, 4],
    [8, 8, 4, 4],
  ],
  files: [
    [0, 1, 5, 2],
    [0, 3, 12, 8],
  ],
  terms: [
    [0, 1, 2, 2],
    [4, 1, 8, 2],
    [0, 5, 2, 2],
    [4, 5, 8, 2],
    [0, 9, 2, 2],
    [4, 9, 8, 2],
  ],
  gear: [
    [5, 0, 2, 2],
    [5, 10, 2, 2],
    [0, 5, 2, 2],
    [10, 5, 2, 2],
    [2, 2, 2, 2],
    [8, 2, 2, 2],
    [2, 8, 2, 2],
    [8, 8, 2, 2],
    [3, 3, 6, 2],
    [3, 7, 6, 2],
    [3, 5, 2, 2],
    [7, 5, 2, 2],
  ],
  back: [
    [6, 1, 2, 2],
    [4, 3, 2, 2],
    [2, 5, 2, 2],
    [4, 7, 2, 2],
    [6, 9, 2, 2],
  ],
};

/**
 * The attribute that keeps edges unsmoothed.
 *
 * It is honoured at runtime but missing from the library's typings.
 */
const CRISP = { shapeRendering: "crispEdges" } as object;

/** Props for the {@link PixelIcon} component. */
export interface PixelIconProps {
  /** Which icon to draw. */
  name: PixelIconName;
  /** Drawn size in points; the grid scales to fit. */
  size?: number;
  /** The fill colour. */
  color: string;
}

/**
 * Render a pixel icon.
 *
 * @param props - The icon, its size and its colour.
 * @returns The icon.
 */
export function PixelIcon({ name, size = 18, color }: PixelIconProps) {
  return (
    <Svg
      width={size}
      height={size}
      viewBox="0 0 12 12"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    >
      {ICONS[name].map(([x, y, w, h], i) => (
        <Rect
          key={i}
          x={x}
          y={y}
          width={w}
          height={h}
          fill={color}
          {...CRISP}
        />
      ))}
    </Svg>
  );
}

export default PixelIcon;
