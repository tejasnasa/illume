/**
 * Themed boolean toggle with accessible switch semantics.
 * @module Switch
 */
import { InputHTMLAttributes } from "react";

type SwitchProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  label?: string;
};

export default function Switch(props: SwitchProps) {
  const isDisabled = props.disabled;
  const labelText = props.label;
  const extraClass = props.className ?? "";

  const checked = props.checked ?? false;
  const disabledClass = isDisabled ? "opacity-50 cursor-not-allowed" : "";

  return (
    <label
      className={`inline-flex items-center gap-2 cursor-pointer select-none ${disabledClass} ${extraClass}`}
    >
      <span className="relative inline-block w-10 h-6 shrink-0">
        <input
          {...props}
          type="checkbox"
          role="switch"
          aria-checked={checked}
          className="peer sr-only"
        />
        <span
          aria-hidden="true"
          className="absolute inset-0 rounded-full bg-(--muted)/60 transition-colors duration-200 peer-checked:bg-(--primary) peer-focus-visible:ring-2 peer-focus-visible:ring-(--ring)"
        />
        <span
          aria-hidden="true"
          className="absolute top-1 left-1 h-4 w-4 rounded-full bg-white shadow transition-transform duration-200 peer-checked:translate-x-4"
        />
      </span>
      {labelText ? (
        <span className="text-sm text-(--foreground)">{labelText}</span>
      ) : null}
    </label>
  );
}
