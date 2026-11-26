/**
 * The list of a repository's chat conversations, as a side panel or a drawer.
 * @module ConversationSidebar
 */
"use client";

import { MAX_TITLE_CHARS } from "@/hooks/useConversationList";
import type { ConversationSummary } from "@/types/conversation";
import { timeAgo } from "@/utils/timeAgo";
import {
  DotsThreeIcon,
  PencilSimpleIcon,
  TrashIcon,
  XIcon,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { ConversationRowsSkeleton } from "./ChatSkeleton";

/** Props for the sidebar. */
export interface ConversationSidebarProps {
  items: ConversationSummary[];
  loaded: boolean;
  /** The open conversation, or null for a new chat. */
  activeId: string | null;
  /** Whether the list is a drawer (narrow screens) rather than a fixed panel. */
  drawer: boolean;
  /** Whether the drawer is showing; ignored for the fixed panel. */
  open: boolean;
  onClose: () => void;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => void | Promise<unknown>;
  onDelete: (id: string) => void | Promise<unknown>;
}

/**
 * One row: the conversation, its menu, and the rename and delete states.
 *
 * @param props - The row's conversation and handlers.
 * @returns The row.
 */
function Row({
  item,
  active,
  onSelect,
  onRename,
  onDelete,
}: {
  item: ConversationSummary;
  active: boolean;
  onSelect: () => void;
  onRename: (title: string) => void | Promise<unknown>;
  onDelete: () => void | Promise<unknown>;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [draft, setDraft] = useState(item.title);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const away = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [menuOpen]);

  const commit = () => {
    const next = draft.trim();
    setRenaming(false);
    if (next && next !== item.title) void onRename(next);
  };

  if (renaming) {
    return (
      <li className="px-2 py-1">
        <input
          autoFocus
          aria-label="Conversation title"
          value={draft}
          maxLength={MAX_TITLE_CHARS}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") commit();
            if (event.key === "Escape") setRenaming(false);
          }}
          className="w-full rounded-sm border border-(--accent) bg-(--background) px-2 py-1.5 text-sm text-(--foreground) focus:outline-none"
        />
      </li>
    );
  }

  if (confirming) {
    return (
      <li
        role="alertdialog"
        aria-label={`Delete ${item.title}`}
        className="mx-2 rounded-sm border border-(--destructive)/30 bg-(--destructive)/5 p-2 text-xs"
      >
        <p className="mb-2 text-(--foreground)">
          Delete this conversation and its messages?
        </p>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => {
              setConfirming(false);
              void onDelete();
            }}
            className="rounded-sm bg-(--destructive) px-2.5 py-1 text-(--primary-foreground) cursor-pointer"
          >
            Delete
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="rounded-sm border border-(--border) px-2.5 py-1 text-(--foreground) cursor-pointer"
          >
            Cancel
          </button>
        </div>
      </li>
    );
  }

  return (
    <li
      className={`group relative mx-2 flex items-center rounded-sm border-l-2 ${active ? "border-(--accent) bg-(--secondary)" : "border-transparent hover:bg-(--secondary)"}`}
    >
      <button
        type="button"
        aria-current={active ? "true" : undefined}
        onClick={onSelect}
        className="min-w-0 flex-1 cursor-pointer px-3 py-2.5 text-left"
      >
        <span
          className={`block truncate text-sm ${active ? "text-(--foreground)" : "text-zinc-400 group-hover:text-(--foreground)"}`}
        >
          {item.title}
        </span>
        <span className="block font-pixel text-[11px] tracking-[0.04em] text-(--faint-foreground) uppercase">
          {timeAgo(item.updated_at)}
        </span>
      </button>
      <div ref={menuRef} className="relative shrink-0 pr-1">
        <button
          type="button"
          aria-label={`Options for ${item.title}`}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((value) => !value)}
          className="rounded-sm p-1.5 text-(--muted-foreground) hover:bg-(--muted) cursor-pointer"
        >
          <DotsThreeIcon size={18} weight="bold" />
        </button>
        {menuOpen && (
          <div
            role="menu"
            className="rise absolute right-0 z-30 mt-1 w-36 rounded-sm border border-(--border) bg-(--card) p-1 shadow-[0_16px_40px_#00000080]"
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                setDraft(item.title);
                setRenaming(true);
              }}
              className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-xs text-(--foreground) hover:bg-(--secondary)/60 cursor-pointer"
            >
              <PencilSimpleIcon size={14} />
              Rename
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                setConfirming(true);
              }}
              className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-xs text-(--destructive) hover:bg-(--destructive)/10 cursor-pointer"
            >
              <TrashIcon size={14} />
              Delete
            </button>
          </div>
        )}
      </div>
    </li>
  );
}

/**
 * Renders the conversation list with a New chat button.
 *
 * On wide screens it is a fixed panel; on narrow ones a drawer that slides over
 * the chat and closes when a conversation is chosen.
 *
 * @param props - The conversations, the active one and the handlers.
 * @returns The panel, or the drawer while it is open.
 */
export default function ConversationSidebar({
  items,
  loaded,
  activeId,
  drawer,
  open,
  onClose,
  onSelect,
  onNew,
  onRename,
  onDelete,
}: ConversationSidebarProps) {
  if (drawer && !open) return null;

  const panel = (
    <nav
      aria-label="Conversations"
      data-testid="conversation-sidebar"
      className={`flex h-full flex-col border-r border-(--border) bg-(--background) ${drawer ? "w-64 shadow-2xl" : "w-full"}`}
    >
      <div className="flex items-center gap-2 p-4">
        <button
          type="button"
          onClick={() => {
            onNew();
            if (drawer) onClose();
          }}
          className="cta flex flex-1 items-center justify-center gap-2 rounded-sm bg-(--primary) px-3 py-2.75 font-pixel text-[13px] tracking-[0.06em] text-(--primary-foreground) uppercase hover:cursor-pointer"
        >
          <span aria-hidden="true">+</span>
          New chat
        </button>
        {drawer && (
          <button
            type="button"
            aria-label="Close conversations"
            onClick={onClose}
            className="rounded-sm p-2 text-(--muted-foreground) hover:bg-(--secondary) cursor-pointer"
          >
            <XIcon size={16} />
          </button>
        )}
      </div>
      <ul className="custom-scrollbar flex-1 space-y-0.5 overflow-y-auto pb-3">
        {!loaded && <ConversationRowsSkeleton />}
        {loaded && items.length === 0 && (
          <li className="px-5 py-2 text-xs text-(--muted-foreground)">
            No conversations yet.
          </li>
        )}
        {items.map((item) => (
          <Row
            key={item.id}
            item={item}
            active={item.id === activeId}
            onSelect={() => {
              onSelect(item.id);
              if (drawer) onClose();
            }}
            onRename={(title) => onRename(item.id, title)}
            onDelete={() => onDelete(item.id)}
          />
        ))}
      </ul>
    </nav>
  );

  if (!drawer) return panel;

  return (
    <div
      className="absolute inset-0 z-40 flex"
      data-testid="conversation-drawer"
    >
      {panel}
      <button
        type="button"
        aria-label="Close conversations"
        tabIndex={-1}
        onClick={onClose}
        className="flex-1 bg-(--background)/60 backdrop-blur-sm cursor-default"
      />
    </div>
  );
}
