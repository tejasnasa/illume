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
          className="absolute inset-0 border border-(--input) bg-(--background) transition-colors duration-200 [transition-timing-function:steps(2)] peer-checked:border-(--accent) peer-checked:bg-(--accent)/15 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-(--ring)"
        />
        <span
          aria-hidden="true"
          className="absolute top-1 left-1 h-4 w-4 bg-(--faint-foreground) transition-transform duration-200 [transition-timing-function:steps(3)] peer-checked:translate-x-4 peer-checked:bg-(--accent)"
        />
      </span>
      {labelText ? (
        <span className="text-sm text-(--foreground)">{labelText}</span>
      ) : null}
    </label>
  );
}
