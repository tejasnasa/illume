/**
 * Click-to-toggle dropdown menu with outside-click dismissal.
 * @module OptionsMenu
 */
"use client";
import { useEffect, useRef, useState } from "react";

/**
 * A single selectable menu row.
 */
interface OptionItem {
  label: string;
  icon?: React.ReactNode;
  destructive?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}

/**
 * Props for the OptionMenu component.
 */
interface OptionMenuProps {
  trigger: React.ReactNode;
  items: OptionItem[];
  size: "sm" | "lg";
  direction: "left" | "right";
  className?: string;
  /**
   * Extra classes applied to the wrapper around the trigger button. The wrapper is
   * `inline-block` by default so the trigger shrinks to its content; pass a block-level
   * class like `w-full` (with a flex/block wrapper) to make the trigger span the parent.
   */
  wrapperClassName?: string;
}

/**
 * Renders a trigger that opens a positioned list of action items.
 * @param trigger The element that toggles the menu when clicked.
 * @param items The menu items rendered as buttons.
 * @param size Size variant controlling item text and icon sizing.
 * @param direction Whether the menu aligns to the left or right edge.
 * @param className Additional class names applied to the menu panel.
 * @returns The rendered menu element.
 */
export default function OptionMenu({
  trigger,
  items,
  size,
  direction,
  className,
  wrapperClassName,
}: OptionMenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // The wrapper is `inline-block` by default so the trigger shrinks to its
  // content (the AutoUpdateSection cadence picker). When the caller passes a
  // wrapperClassName like `block w-full`, swap the display value so the
  // trigger can fill its parent without the inline-block rule winning the
  // CSS cascade. The caller controls the layout; we just defer to it.
  const displayClass = wrapperClassName ?? "inline-block";

  return (
    <div className={`relative ${displayClass}`} ref={ref}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        // `w-full` so the trigger fills its block-level wrapper (used by the
        // BYOK provider picker); inline callers that don't pass `wrapperClassName`
        // already get a content-sized button from the default `inline-block`.
        className={`${wrapperClassName ? "w-full" : ""} block border-0 bg-transparent p-0`}
      >
        {trigger}
      </button>

      {open && (
        <div
          className={`absolute z-50 mt-1 rounded-sm border border-(--border) bg-(--card) shadow-xl shadow-(--primary)/5 p-1.5 backdrop-blur-xl ${direction === "left" ? "right-0" : "left-0"} ${className || ""}`}
          style={{ animation: "scale-in 0.15s ease-out" }}
        >
          {items.map((item, i) => (
            <button
              key={i}
              disabled={item.disabled}
              onClick={() => {
                item.onClick?.();
                setOpen(false);
              }}
              className={`flex w-full items-center gap-2.5 rounded-xs px-3 py-2 transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-40 hover:cursor-pointer whitespace-nowrap
                ${size === "sm" && "text-xs"}
                ${size === "lg" && "text-sm"}
                ${
                  item.destructive
                    ? "text-(--destructive) hover:bg-(--destructive)/10"
                    : "text-(--foreground) hover:bg-(--muted)/60"
                }`}
            >
              {item.icon && (
                <span
                  className={`shrink-0
                    ${size === "sm" && "w-4 h-4"}
                    ${size === "lg" && "w-5 h-5"}`}
                >
                  {item.icon}
                </span>
              )}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
