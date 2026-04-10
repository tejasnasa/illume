"use client";
import { useEffect, useRef, useState } from "react";

interface OptionItem {
  label: string;
  icon?: React.ReactNode;
  destructive?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}

interface OptionMenuProps {
  trigger: React.ReactNode;
  items: OptionItem[];
  size: "sm" | "lg";
  direction: "left" | "right";
  className?: string;
}

export default function OptionMenu({
  trigger,
  items,
  size,
  direction,
  className,
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

  return (
    <div className="relative inline-block" ref={ref}>
      <div onClick={() => setOpen((o) => !o)}>{trigger}</div>

      {open && (
        <div
          className={`absolute z-50 mt-1 rounded-xl border border-(--border) bg-(--card) shadow-xl shadow-(--primary)/5 p-1.5 backdrop-blur-xl ${direction === "left" ? "right-0" : "left-0"} ${className || ""}`}
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
              className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-40 hover:cursor-pointer
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
