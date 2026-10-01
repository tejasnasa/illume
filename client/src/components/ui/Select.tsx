/**
 * Custom select-over-a-listbox, styled from the app's own tokens.
 * @module Select
 */
"use client";

import { CaretDownIcon, CheckIcon } from "@phosphor-icons/react/dist/ssr";
import { useEffect, useRef, useState } from "react";

/** One choice in the list. */
export type SelectOption = {
  value: string;
  label: string;
};

type Props = {
  /** Field id, also used to derive the listbox id. */
  id: string;
  /** Field label, rendered above the control. */
  label: string;
  /** Currently selected value, or `""` for none. */
  value: string;
  /** Called with the newly chosen value. */
  onChange: (value: string) => void;
  /** The choices, in display order. */
  options: readonly SelectOption[];
  /** Shown on the trigger while nothing is selected. */
  placeholder?: string;
};

/**
 * Renders a select as a button that opens a listbox.
 *
 * Deliberately **not** a native `<select>`. The list a native select opens is drawn by the
 * operating system, not the page, so it cannot be reached from CSS at all -- not by a
 * `bg-*` class, and not by `color-scheme` on the document, which the platform is free to
 * ignore. On a dark-only interface that means a light popup no amount of styling fixes.
 * The rest of this app's dropdowns avoid the problem the same way, by drawing the panel
 * themselves.
 *
 * The cost of leaving the native element behind is that its behaviour has to be rebuilt, so
 * this is a `combobox`/`listbox` pair rather than a menu: the trigger keeps focus while the
 * list is open, arrow keys move a highlight through it, Enter takes the highlighted choice,
 * and Escape closes without choosing. `aria-activedescendant` -- not focus -- is what tells
 * assistive technology which row is highlighted, which is the pattern a select-only
 * combobox is specified to use.
 *
 * @param id - Field id, also used to derive the listbox id.
 * @param label - Field label, rendered above the control.
 * @param value - Currently selected value, or `""` for none.
 * @param onChange - Called with the newly chosen value.
 * @param options - The choices, in display order.
 * @param placeholder - Shown on the trigger while nothing is selected.
 * @returns The rendered field.
 */
export default function Select({
  id,
  label,
  value,
  onChange,
  options,
  placeholder = "Select an option",
}: Props) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const labelId = `${id}-label`;
  const listboxId = `${id}-listbox`;
  const optionId = (index: number) => `${id}-option-${index}`;

  const selected = options.find((option) => option.value === value);

  // Dismiss on a click anywhere outside. `mousedown` rather than `click` so the panel
  // closes as the press lands, before the click it belongs to resolves on another element.
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  /** Opens the list with the current selection highlighted. */
  function openList() {
    setActiveIndex(options.findIndex((option) => option.value === value));
    setOpen(true);
  }

  /** Takes a choice and closes. */
  function choose(next: string) {
    onChange(next);
    setOpen(false);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (!open) {
      // Enter and Space are left to the button's own click, which already toggles.
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        openList();
      }
      return;
    }

    switch (event.key) {
      case "Escape":
        setOpen(false);
        break;
      case "Tab":
        // Moving on rather than choosing: a Tab out of an open list should not commit the
        // highlighted row, which the user may never have looked at.
        setOpen(false);
        break;
      case "ArrowDown":
        event.preventDefault();
        setActiveIndex((index) => Math.min(index + 1, options.length - 1));
        break;
      case "ArrowUp":
        event.preventDefault();
        setActiveIndex((index) => Math.max(index - 1, 0));
        break;
      case "Enter":
      case " ":
        // preventDefault so the button's own click does not also fire and toggle the list
        // shut instead of choosing.
        event.preventDefault();
        if (activeIndex >= 0) choose(options[activeIndex].value);
        break;
    }
  }

  return (
    <div className="flex flex-col gap-1" ref={wrapperRef}>
      <span id={labelId} className="text-sm">
        {label}
      </span>

      <div className="relative">
        <button
          type="button"
          id={id}
          role="combobox"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-labelledby={`${labelId} ${id}`}
          aria-activedescendant={open && activeIndex >= 0 ? optionId(activeIndex) : undefined}
          onClick={() => (open ? setOpen(false) : openList())}
          onKeyDown={handleKeyDown}
          className="w-full h-11 rounded-sm pl-4 pr-10 text-sm text-left border border-(--border) bg-(--muted)/50 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--ring) focus-visible:border-(--primary)/30 transition-all duration-200"
        >
          <span className={selected ? "text-(--foreground)" : "text-(--muted-foreground)/50"}>
            {selected?.label ?? placeholder}
          </span>
        </button>

        <CaretDownIcon
          aria-hidden="true"
          size={16}
          className={`pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-(--muted-foreground) transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        />

        {open && (
          <ul
            role="listbox"
            id={listboxId}
            aria-labelledby={labelId}
            className="absolute z-50 left-0 right-0 mt-1 rounded-sm border border-(--border) bg-(--card) shadow-xl shadow-(--primary)/5 p-1.5 backdrop-blur-xl"
            style={{ animation: "scale-in 0.15s ease-out" }}
          >
            {options.map((option, index) => (
              <li
                key={option.value}
                id={optionId(index)}
                role="option"
                aria-selected={option.value === value}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => choose(option.value)}
                className={`flex w-full items-center justify-between gap-2.5 rounded-xs px-3 py-2 text-sm cursor-pointer transition-all duration-150 ${
                  index === activeIndex ? "bg-(--muted)/60" : ""
                }`}
              >
                {option.label}
                {option.value === value && (
                  <CheckIcon
                    aria-hidden="true"
                    size={14}
                    className="shrink-0 text-(--primary)"
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
