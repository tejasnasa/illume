/**
 * Styled multi-line textarea with a fixed height.
 * @module Textarea
 */
import { TextareaHTMLAttributes } from "react";

/** Fixed heights the textarea can take. */
const HEIGHTS = {
  sm: "h-32",
  lg: "h-56",
} as const;

type Props = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  /** Fixed height. Defaults to `sm`. */
  size?: keyof typeof HEIGHTS;
};

/**
 * Renders a themed non-resizable textarea forwarding all native attributes.
 *
 * The height is a prop rather than something a caller overrides with `className`. Both
 * classes set the same property, so which one wins depends on the order the generated
 * stylesheet emits them -- not on the order they appear in the attribute, which is the
 * assumption a `className="h-56"` override silently relies on. It happens to work until
 * it does not.
 *
 * @param className Additional class names appended to the base styles.
 * @param size Fixed height for the field.
 * @param props Remaining native textarea attributes.
 * @returns The rendered textarea element.
 */
export default function Textarea({
  className = "",
  size = "sm",
  ...props
}: Props) {
  return (
    <textarea
      {...props}
      className={`${HEIGHTS[size]} rounded-sm border border-(--input) bg-(--background) px-3 py-2.5 text-sm leading-relaxed transition-colors duration-150 resize-none placeholder:text-(--faint-foreground) focus-visible:border-(--accent) focus-visible:outline-none ${className}`}
    ></textarea>
  );
}
