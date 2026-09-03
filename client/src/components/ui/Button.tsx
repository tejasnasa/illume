/**
 * Primary button with size variants and a loading state.
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
};

const sizes = {
  xs: "px-2.5 py-1 text-xs",
  sm: "px-4 py-2 text-sm",
  md: "h-11 px-5 text-sm",
  lg: "h-12 px-6 text-base",
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
 * @param props Remaining native button attributes including children.
 * @returns The rendered button element.
 */
export default function Button({
  className = "",
  size = "md",
  ratio,
  style,
  loading = false,
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
      className={`bg-(--primary) text-(--primary-foreground) hover:cursor-pointer hover:scale-[1.02] transform rounded-sm transition-all duration-200 active:translate-y-0.5 inline-flex items-center justify-center gap-2 font-medium disabled:bg-(--primary)/40 disabled:cursor-default ${base} ${ratio ? "px-0" : ""} ${className}`}
    >
      {loading && <SpinnerIcon className={`animate-spin ${iconSizes[size]}`} />}
      {props.children}
    </button>
  );
}
