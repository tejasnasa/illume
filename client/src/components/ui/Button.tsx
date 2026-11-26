/**
 * Pixel-labelled button with size and colour variants and a loading state.
 * @module Button
 */
import { SpinnerIcon } from "@phosphor-icons/react/dist/ssr";

/**
 * Props for the Button component.
 */
type Props = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  size?: "xs" | "sm" | "md" | "lg";
  ratio?: number;
  loading?: boolean;
  variant?: "primary" | "ghost" | "danger";
};

const sizes = {
  xs: "h-7 px-2.5 text-[11px]",
  sm: "h-9 px-3.5 text-xs",
  md: "h-11 px-5 text-[13px]",
  lg: "h-12 px-6 text-sm",
};

const variants = {
  primary:
    "cta bg-(--primary) text-(--primary-foreground) border border-transparent disabled:bg-(--primary)/40",
  ghost:
    "ghost bg-transparent text-zinc-300 border border-(--input) disabled:opacity-50",
  danger:
    "bg-transparent text-red-400 border border-red-500/40 transition-colors hover:bg-red-500/10 disabled:opacity-50",
};

const iconSizes = {
  xs: "h-2.5 w-2.5",
  sm: "h-3 w-3",
  md: "h-4 w-4",
  lg: "h-5 w-5",
};

/**
 * Renders a styled button that shows a spinner and disables itself while loading.
 * @param className Additional class names appended to the base styles.
 * @param size Size variant controlling padding, height, and icon size.
 * @param ratio Optional aspect ratio applied via inline style.
 * @param style Inline styles merged with the aspect-ratio style.
 * @param loading When true, shows a spinner and disables the button.
 * @param variant Filled primary, outlined ghost, or outlined destructive.
 * @param props Remaining native button attributes including children.
 * @returns The rendered button element.
 */
export default function Button({
  className = "",
  size = "md",
  ratio,
  style,
  loading = false,
  variant = "primary",
  ...props
}: Props) {
  const base = sizes[size];

  return (
    <button
      {...props}
      style={{
        ...style,
        ...(ratio && { aspectRatio: ratio }),
      }}
      disabled={loading || props.disabled}
      className={`${variants[variant]} inline-flex items-center justify-center gap-2 rounded-sm font-pixel tracking-[0.06em] uppercase hover:cursor-pointer active:translate-y-px disabled:cursor-default ${base} ${ratio ? "px-0" : ""} ${className}`}
    >
      {loading && <SpinnerIcon className={`animate-spin ${iconSizes[size]}`} />}
      {props.children}
    </button>
  );
}
