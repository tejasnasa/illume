/**
 * Styled single-line text input.
 * @module Input
 */
import { InputHTMLAttributes } from "react";

/**
 * Renders a themed input forwarding all native attributes.
 * @param className Additional class names appended to the base styles.
 * @param props Remaining native input attributes.
 * @returns The rendered input element.
 */
export default function Input({
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`h-11 rounded-sm border border-(--input) bg-(--background) px-3 text-sm text-(--foreground) transition-colors duration-150 placeholder:text-(--faint-foreground) focus-visible:border-(--accent) focus-visible:outline-none disabled:opacity-60 ${className}`}
    />
  );
}
