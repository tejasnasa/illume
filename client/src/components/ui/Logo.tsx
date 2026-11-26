/**
 * The Illume mark: a blue hub with three spokes, one of them ending in pink.
 * @module Logo
 */

/**
 * Props for the Logo component.
 */
type Props = {
  size?: number;
  className?: string;
};

/**
 * Renders the mark as inline SVG so it inherits no font metrics and scales crisply.
 *
 * Decorative by default: every caller places it inside a link or next to the
 * word "illume", which already names it.
 *
 * @param size Rendered width and height in pixels.
 * @param className Extra classes for the svg element.
 * @returns The logo mark.
 */
export default function Logo({ size = 30, className }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 120 120"
      aria-hidden="true"
      className={className}
    >
      <g stroke="#fafafa" strokeWidth="6" strokeLinecap="round">
        <line x1="60" y1="60" x2="24" y2="28" />
        <line x1="60" y1="60" x2="98" y2="34" />
        <line x1="60" y1="60" x2="50" y2="102" />
      </g>
      <circle cx="24" cy="28" r="10" fill="#fafafa" />
      <circle cx="50" cy="102" r="10" fill="#fafafa" />
      <circle cx="98" cy="34" r="10" fill="var(--accent)" />
      <circle cx="60" cy="60" r="19" fill="var(--selected)" />
    </svg>
  );
}

/**
 * The mark followed by the lowercase wordmark, as used in the top bars.
 *
 * @returns The lockup.
 */
export function Wordmark() {
  return (
    <span className="flex items-center gap-2.5 text-(--foreground)">
      <Logo />
      <span className="font-pixel text-[22px] leading-none">illume</span>
    </span>
  );
}
