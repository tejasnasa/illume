/**
 * Shimmer placeholder block for loading content.
 * @module Skeleton
 */

/**
 * Renders an animated shimmer placeholder.
 * @param className Additional class names controlling size and spacing.
 * @param style Inline styles, for a size computed at render time.
 * @returns The rendered skeleton element.
 */
export default function Skeleton({
  className = "",
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      aria-hidden="true"
      style={style}
      className={`bg-linear-to-r from-(--muted)/40 via-(--muted)/70 to-(--muted)/40 animate-shimmer rounded-sm ${className}`}
    />
  );
}
