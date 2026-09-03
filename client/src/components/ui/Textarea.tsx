/**
 * Styled multi-line textarea with fixed height.
 * @module Textarea
 */
import { TextareaHTMLAttributes } from "react";

/**
 * Renders a themed non-resizable textarea forwarding all native attributes.
 * @param className Additional class names appended to the base styles.
 * @param props Remaining native textarea attributes.
 * @returns The rendered textarea element.
 */
export default function Textarea({
  className,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={`bg-(--muted)/50 h-32 rounded-sm px-4 py-3 text-sm border border-(--border) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--ring) focus-visible:border-(--primary)/30 transition-all duration-200 resize-none placeholder:text-(--muted-foreground)/50 ${className}`}
    ></textarea>
  );
}
