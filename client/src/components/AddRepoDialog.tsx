/**
 * The dashboard's "Add repository" button and the picker dialog it opens.
 * @module AddRepoDialog
 */
"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import RepoPickerModal from "./RepoPickerModal";

/**
 * Renders the add-repository call to action and, when open, the picker.
 *
 * The dialog owns its open state rather than using the shared `Modal`,
 * because the picker draws its own header with a close button and needs to
 * close itself once an ingest has started.
 *
 * @param note Optional cost line passed to the version step.
 * @param added URLs of the repositories already on the dashboard.
 * @returns The trigger and, while open, the portal dialog.
 */
export default function AddRepoDialog({
  note,
  added,
}: {
  note?: string;
  added?: string[];
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  /** Closes the dialog and hands focus back to the trigger. */
  const close = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [open]);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
        className="cta rounded-sm bg-(--primary) px-5 py-3 font-pixel text-[13px] tracking-[0.06em] text-(--primary-foreground) uppercase hover:cursor-pointer"
      >
        <span aria-hidden="true">+ </span>Add repository
      </button>

      {open &&
        createPortal(
          <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:items-center">
            <div
              aria-hidden="true"
              className="fixed inset-0 bg-[#050507cc] backdrop-blur-sm"
              onClick={close}
            />
            <div
              role="dialog"
              aria-modal="true"
              aria-label="Add a repository"
              className="rise relative flex h-[min(80dvh,760px)] w-full max-w-180 flex-col overflow-hidden rounded-md border border-(--input) bg-(--card) shadow-[0_30px_80px_#000000a6]"
            >
              <RepoPickerModal onClose={close} note={note} added={added} />
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
