import { InputHTMLAttributes } from "react";

export default function Input({
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`bg-(--muted)/50 h-11 rounded-xl px-4 py-3 text-sm border border-(--border) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--ring) focus-visible:border-(--primary)/30 transition-all duration-200 placeholder:text-(--muted-foreground)/50 ${className}`}
    />
  );
}
