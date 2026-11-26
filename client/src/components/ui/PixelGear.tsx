/**
 * An eight-by-eight pixel gear, drawn with crisp edges.
 * @module PixelGear
 */

/**
 * Renders the gear in `currentColor`, with a hole punched through the middle.
 *
 * The hole is a mask rather than a filled square so the icon stays correct on
 * any background.
 *
 * @param size Rendered width and height in pixels.
 * @returns The decorative gear icon.
 */
export default function PixelGear({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 8 8"
      shapeRendering="crispEdges"
      fill="currentColor"
      aria-hidden="true"
    >
      <path
        fillRule="evenodd"
        d="M3 0h2v1H3zM3 7h2v1H3zM0 3h1v2H0zM7 3h1v2H7zM1 1h6v6H1zM3 3v2h2V3z"
      />
    </svg>
  );
}
