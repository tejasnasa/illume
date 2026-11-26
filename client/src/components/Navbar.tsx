/**
 * Top bar for the signed-in pages outside a repository: wordmark, a breadcrumb
 * naming the current page, and the account menu.
 * @module Navbar
 */
"use client";

import { useLogout } from "@/hooks/useLogout";
import User from "@/types/user";
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { Wordmark } from "./ui/Logo";

/**
 * Up to two initials from a display name, for the avatar tile.
 *
 * @param name The display name, or a fallback handle.
 * @returns Uppercase initials, never empty.
 */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const letters =
    parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[1][0];
  return letters.toUpperCase();
}

const MENU_LINKS = [
  { href: "/settings", label: "Settings" },
  { href: "/contact", label: "Contact" },
] as const;

/**
 * Renders the top bar with the breadcrumb and the account dropdown.
 *
 * The menu closes on an outside click, on Escape (returning focus to its
 * button) and whenever an item is chosen.
 *
 * @param userData - Current user for the avatar and name; falls back to defaults.
 * @param page - Label of the current page, shown after the wordmark.
 * @returns Sticky header with the account menu.
 */
export default function Navbar({
  userData = null,
  page,
}: {
  userData?: User | null;
  page?: string;
}) {
  const logout = useLogout();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  // `github_id` is GitHub's numeric account id, not a login, so it is never
  // shown; the email is the one identifier every account has.
  const name = userData?.name || userData?.email || "User";
  const email = userData?.email || null;

  useEffect(() => {
    if (!open) return;
    function onPointer(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const itemClass =
    "rounded-sm px-3 py-2.5 text-left font-pixel text-[13px] tracking-[0.06em] uppercase transition-colors duration-150 hover:bg-(--secondary)";

  return (
    <nav
      aria-label="Main"
      className="sticky top-0 z-40 border-b border-(--border) bg-(--background)/85 backdrop-blur-md print:hidden"
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
        <div className="flex min-w-0 items-center gap-3.5">
          <Link href="/dashboard" aria-label="Dashboard">
            <Wordmark />
          </Link>
          {page && (
            <>
              <span aria-hidden="true" className="text-zinc-700">
                /
              </span>
              <span className="truncate font-pixel text-base">{page}</span>
            </>
          )}
        </div>

        <div ref={wrapRef} className="relative">
          <button
            ref={buttonRef}
            type="button"
            aria-label="Account menu"
            aria-haspopup="menu"
            aria-expanded={open}
            aria-controls={open ? menuId : undefined}
            onClick={() => setOpen((o) => !o)}
            className="flex items-center gap-2.5 rounded-sm border border-(--border) bg-(--card) py-1 pr-2.5 pl-1 transition-colors hover:border-(--border-strong) hover:cursor-pointer"
          >
            {userData?.avatar_url ? (
              // A plain img: avatars come from GitHub's CDN at whatever size it
              // serves, and a 28px tile gains nothing from the image optimiser.
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={userData.avatar_url}
                alt=""
                width={28}
                height={28}
                className="h-7 w-7 object-cover"
              />
            ) : (
              <span
                aria-hidden="true"
                className="flex h-7 w-7 items-center justify-center bg-(--primary) font-pixel text-[13px] text-(--primary-foreground)"
              >
                {initials(name)}
              </span>
            )}
            <span className="hidden max-w-40 truncate text-sm sm:block">
              {name}
            </span>
            <span
              aria-hidden="true"
              className="font-pixel text-xs text-(--subtle-foreground)"
            >
              {open ? "▴" : "▾"}
            </span>
          </button>

          {open && (
            <div
              id={menuId}
              role="menu"
              aria-label="Account"
              className="rise absolute top-[calc(100%+8px)] right-0 z-50 flex w-56 flex-col rounded-md border border-(--border) bg-(--card) p-1.5 shadow-[0_16px_40px_#00000080]"
            >
              <div className="mb-1.5 flex flex-col gap-0.5 border-b border-white/8 px-3 pt-2.5 pb-3">
                <span className="truncate text-sm">{name}</span>
                {email && email !== name && (
                  <span className="truncate text-xs text-(--subtle-foreground)">
                    {email}
                  </span>
                )}
              </div>
              {MENU_LINKS.map(({ href, label }) => (
                <Link
                  key={href}
                  role="menuitem"
                  href={href}
                  onClick={() => setOpen(false)}
                  className={`${itemClass} text-zinc-300 hover:text-(--foreground)`}
                >
                  {label}
                </Link>
              ))}
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  void logout();
                }}
                className={`${itemClass} text-red-400 hover:cursor-pointer`}
              >
                Log out
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
}
