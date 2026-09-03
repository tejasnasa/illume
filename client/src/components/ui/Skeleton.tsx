/**
 * Shimmer placeholder block for loading content.
 * @module Skeleton
 */

/**
 * Renders an animated shimmer placeholder.
 * @param className Additional class names controlling size and spacing.
 * @returns The rendered skeleton element.
 */
export default function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`bg-linear-to-r from-(--muted)/40 via-(--muted)/70 to-(--muted)/40 animate-shimmer rounded-sm ${className}`}
    />
  );
}
