/**
 * Trigger-driven modal dialog rendered via a React portal.
 * @module Modal
 */
"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

/**
 * Props for the Modal component.
 */
type Props = {
  trigger: React.ReactNode;
  children: React.ReactNode;
  className?: string;
};

/**
 * Renders a clickable trigger that opens dialog content in a portal overlay.
 * @param trigger The element that opens the modal when clicked.
 * @param children The dialog content rendered inside the modal panel.
 * @param className Additional class names applied to the modal panel.
 * @returns The rendered trigger and conditional portal element.
 */
export default function Modal({ trigger, children, className = "" }: Props) {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    function handleEsc(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    if (open) document.addEventListener("keydown", handleEsc);
    return () => document.removeEventListener("keydown", handleEsc);
  }, [open]);

  return (
    <>
      <div
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        className="inline-flex w-full sm:w-auto h-full"
      >
        {trigger}
      </div>

      {open &&
        mounted &&
        createPortal(
          <div className="fixed inset-0 z-50 flex items-center justify-center">
            <div
              className="absolute inset-0 bg-(--background)/60 backdrop-blur-md"
              onClick={() => setOpen(false)}
              style={{ animation: "fade-in 0.2s ease-out" }}
            />

            <div
              className="relative z-51"
              style={{ animation: "scale-in 0.3s ease-out" }}
              onClick={(e) => {
                const target = e.target as HTMLElement | null;
                // Close when content uses the alert-dialog opt-out attribute.
                if (target?.closest("[data-alert-dialog-close]")) {
                  setOpen(false);
                }
              }}
            >
              <div className={`relative z-50 w-min-120 rounded-sm border border-(--border) bg-(--card) shadow-2xl p-6 ${className}`}>
                {children}
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
