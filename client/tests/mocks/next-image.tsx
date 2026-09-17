/**
 * Stand-in for `next/image` in tests.
 *
 * The real component calls `getImgProps`, which throws outside a Next.js build, so any
 * component rendering an image fails to mount. This renders a plain `<img>` and drops
 * the Next-specific props (`fill`, `priority`, `loader`, ...) that would otherwise be
 * spread onto the DOM node and produce React warnings.
 */
type NextImageProps = {
  src: string | { src: string };
  alt: string;
  fill?: boolean;
  priority?: boolean;
  loader?: unknown;
  placeholder?: unknown;
  blurDataURL?: string;
  sizes?: string;
  quality?: number;
  unoptimized?: boolean;
} & Record<string, unknown>;

const NEXT_ONLY_PROPS = new Set([
  "fill",
  "priority",
  "loader",
  "placeholder",
  "blurDataURL",
  "quality",
  "unoptimized",
]);

export default function NextImage({ src, alt, ...rest }: NextImageProps) {
  // Filtered rather than destructured-and-discarded: naming the dropped props only to
  // never read them trips the unused-vars rule.
  const imgProps = Object.fromEntries(
    Object.entries(rest).filter(([key]) => !NEXT_ONLY_PROPS.has(key)),
  );

  const resolved = typeof src === "string" ? src : src?.src;

  // eslint-disable-next-line @next/next/no-img-element
  return <img src={resolved} alt={alt} {...imgProps} />;
}
