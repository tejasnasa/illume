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
  label?: string;
  dialogLabel?: string;
};

/**
 * Renders a clickable trigger that opens dialog content in a portal overlay.
 * @param trigger The element that opens the modal when clicked.
 * @param children The dialog content rendered inside the modal panel.
 * @param className Additional class names applied to the modal panel.
 * @param label Accessible name, for a trigger that is not already a control.
 * @param dialogLabel Accessible name for the dialog; defaults to `label`.
 * @returns The rendered trigger and conditional portal element.
 */
export default function Modal({
  trigger,
  children,
  className = "",
  label,
  dialogLabel,
}: Props) {
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

  const triggerClassName = "inline-flex w-full sm:w-auto h-full";
  const openModal = (e: React.MouseEvent) => {
    e.stopPropagation();
    setOpen(true);
  };

  return (
    <>
      {label ? (
        <button
          type="button"
          aria-label={label}
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={openModal}
          className={triggerClassName}
        >
          {trigger}
        </button>
      ) : (
        <div onClick={openModal} className={triggerClassName}>
          {trigger}
        </div>
      )}

      {open &&
        mounted &&
        createPortal(
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="absolute inset-0 bg-[#050507cc] backdrop-blur-sm"
              onClick={() => setOpen(false)}
              style={{ animation: "fade-in 0.2s ease-out" }}
            />

            <div
              className="relative z-51"
              style={{ animation: "rise 0.18s steps(3) both" }}
              onClick={(e) => {
                const target = e.target as HTMLElement | null;
                // Close when content uses the alert-dialog opt-out attribute.
                if (target?.closest("[data-alert-dialog-close]")) {
                  setOpen(false);
                }
              }}
            >
              <div
                role="dialog"
                aria-modal="true"
                aria-label={dialogLabel ?? label}
                className={`relative z-50 max-h-[calc(100dvh-2rem)] overflow-y-auto rounded-md border border-(--input) bg-(--card) p-6 shadow-[0_30px_80px_#000000a6] ${className}`}
              >
                {children}
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
