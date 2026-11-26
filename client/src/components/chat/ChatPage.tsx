/**
 * The fullscreen chat: live graph, message column and floating input.
 * @module ChatPage
 */
"use client";

import { useConversation } from "@/hooks/useConversation";
import { useConversationList } from "@/hooks/useConversationList";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { laneColor } from "@/lib/agent/palette";
import {
  buildOverrides,
  defaultSettings,
  isCustom,
  defaultPreset,
  loadChoice,
  presetAvailability,
  saveChoice,
  type Capabilities,
  type DrawerSettings,
  type PresetChoice,
  type PresetId,
} from "@/lib/agent/presets";
import { useRepoGraph } from "@/components/RepoGraphContext";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AdvancedDrawer from "./AdvancedDrawer";
import ChatInput from "./ChatInput";
import ConversationSidebar from "./ConversationSidebar";
import { GreetingSkeleton, SuggestionsSkeleton } from "./ChatSkeleton";
import PresetPicker from "./PresetPicker";
import TurnView from "./TurnView";

// The graph is never imported on a phone: this module only loads once the
// component renders, and it renders only when the screen is wide.
const LiveGraph = dynamic(() => import("./LiveGraph"), { ssr: false });

/** Props the page needs from the server component. */
export interface ChatPageProps {
  repoId: string;
  repoName: string;
  url: string;
  commitSha: string | null;
  branch: string | null;
  suggestions: string[];
  caps: Capabilities;
  /** Free chat questions left, or null when the quota does not apply. */
  freeChatRemaining: number | null;
  /** The conversation named by the address (`?c=`), or null for a new chat. */
  initialConversationId?: string | null;
  /** A question to start the composer with (`?q=`), as other pages link here. */
  initialQuestion?: string;
}

/** Query parameter holding the open conversation. */
const CONVERSATION_PARAM = "c";

/**
 * Points the address at a conversation, or at a new chat, without a reload.
 *
 * @param id - The conversation, or null for a new chat.
 * @param mode - `push` adds a history entry; `replace` rewrites the current one.
 */
function writeConversationUrl(id: string | null, mode: "push" | "replace") {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set(CONVERSATION_PARAM, id);
  else url.searchParams.delete(CONVERSATION_PARAM);
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next === current) return;
  if (mode === "push") window.history.pushState(null, "", next);
  else window.history.replaceState(null, "", next);
}

/** The conversation the address names right now. */
function readConversationUrl(): string | null {
  return new URLSearchParams(window.location.search).get(CONVERSATION_PARAM);
}

/** Distance from the bottom, in pixels, within which the column keeps following. */
const FOLLOW_THRESHOLD = 96;

/**
 * Renders the chat page for one repository.
 *
 * @param props - Repository identity, suggestions and account capabilities.
 * @returns The page.
 */
export default function ChatPage({
  repoId,
  repoName,
  url,
  commitSha,
  branch,
  suggestions,
  caps,
  freeChatRemaining,
  initialConversationId = null,
  initialQuestion = "",
}: ChatPageProps) {
  const reduced = useReducedMotion();
  const wide = useMediaQuery("(min-width: 768px)");
  const graph = useRepoGraph();
  const list = useConversationList(repoId);
  const { refresh: refreshList } = list;
  const missingRef = useRef<() => void>(() => {});
  const conversation = useConversation(repoId, initialConversationId, {
    onTurnSaved: (id, created) => {
      if (created) writeConversationUrl(id, "replace");
      void refreshList();
    },
    onMissing: () => missingRef.current(),
  });
  const { turns, busy, focusState, loaded } = conversation;
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const [input, setInput] = useState(initialQuestion);
  const [choice, setChoice] = useState<PresetChoice>(() => defaultPreset(caps));
  const [settings, setSettings] = useState<DrawerSettings | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [pulsePath, setPulsePath] = useState<string | null>(null);
  const [atBottom, setAtBottom] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const jumpingRef = useRef(false);
  const answered = useRef(new Set<string>());
  const [answeredCount, setAnsweredCount] = useState(0);

  // The remembered choice is read after mount: storage does not exist on the server.
  useEffect(() => {
    const stored = loadChoice(repoId);
    if (!stored) return;
    if (!presetAvailability(stored.preset, caps).available) return;
    setChoice(stored.preset);
    setSettings(stored.settings);
    // Only on first load for this repository.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId]);

  // The drawer tunes a concrete preset; under Auto it starts from the account's
  // default one, and Auto itself sends no overrides because the server has not
  // yet chosen the preset they would apply to.
  const preset: PresetId = choice === "auto" ? defaultPreset(caps) : choice;
  const effective = settings ?? defaultSettings(preset);
  const custom = choice !== "auto" && isCustom(preset, effective);

  const remember = useCallback(
    (nextChoice: PresetChoice, nextSettings: DrawerSettings | null) => {
      setChoice(nextChoice);
      setSettings(nextSettings);
      saveChoice(repoId, { preset: nextChoice, settings: nextSettings });
    },
    [repoId],
  );

  // Back and forward move between conversations without a reload.
  const { select } = conversation;
  missingRef.current = () => {
    writeConversationUrl(null, "replace");
    select(null);
  };
  useEffect(() => {
    const onPop = () => select(readConversationUrl());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [select]);

  const openConversation = useCallback(
    (id: string | null) => {
      if (id === conversation.activeId) return;
      writeConversationUrl(id, "push");
      select(id);
    },
    [conversation.activeId, select],
  );

  const { remove: removeConversation } = list;
  const deleteConversation = useCallback(
    async (id: string) => {
      if (id === conversation.activeId) {
        writeConversationUrl(null, "replace");
        select(null);
      }
      await removeConversation(id);
    },
    [conversation.activeId, select, removeConversation],
  );

  // Free-tier questions answered in this visit, so the allowance note stays current.
  useEffect(() => {
    for (const turn of turns) {
      if (
        turn.inFocus &&
        turn.run.status === "done" &&
        !answered.current.has(turn.id)
      ) {
        answered.current.add(turn.id);
        setAnsweredCount(answered.current.size);
      }
    }
  }, [turns]);

  const remaining =
    freeChatRemaining === null
      ? null
      : Math.max(0, freeChatRemaining - answeredCount);
  const quotaExhausted = remaining !== null && remaining <= 0;

  const empty = turns.length === 0;

  const send = useCallback(
    (question?: string) => {
      const text = (question ?? input).trim();
      if (!text || busy || quotaExhausted) return;
      stickRef.current = true;
      conversation.send(
        text,
        choice,
        choice === "auto" ? undefined : buildOverrides(preset, effective),
      );
      setInput("");
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [input, busy, quotaExhausted, choice, preset, effective, conversation.send],
  );

  // Follow the newest content until the reader scrolls away.
  const lastTurn = turns[turns.length - 1];
  const signature = lastTurn
    ? `${turns.length}:${lastTurn.run.rows.length}:${lastTurn.run.answer.length}:${lastTurn.run.status}`
    : "0";
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !stickRef.current) return;
    // Instant: a smooth scroll passes through positions far from the bottom,
    // and the scroll handler would read those as the reader scrolling away.
    el.scrollTop = el.scrollHeight;
  }, [signature]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const near =
      el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_THRESHOLD;
    // A jump in progress is not the reader scrolling away.
    if (jumpingRef.current) {
      if (near) jumpingRef.current = false;
      return;
    }
    stickRef.current = near;
    setAtBottom(near);
  };

  // Content can shrink or grow without a scroll event (history arriving, a
  // turn being deleted, a row collapsing), so the pill is re-evaluated on
  // resize too. While following, growth also keeps the newest line in view.
  const columnRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = scrollRef.current;
    const column = columnRef.current;
    if (!el || !column || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (stickRef.current) {
        el.scrollTop = el.scrollHeight;
        setAtBottom(true);
        return;
      }
      setAtBottom(
        el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_THRESHOLD,
      );
    });
    observer.observe(column);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const jumpToLatest = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickRef.current = true;
    jumpingRef.current = !reduced;
    setAtBottom(true);
    el.scrollTo({
      top: el.scrollHeight,
      behavior: reduced ? "auto" : "smooth",
    });
  };

  const laneColors = useMemo(() => {
    const out: Record<string, string> = {};
    for (const id of focusState.laneOrder) {
      out[id] = laneColor(focusState.lanes[id].colorIndex);
    }
    return out;
  }, [focusState.laneOrder, focusState.lanes]);

  const repoRef = { url, commitSha, branch };
  const showGraph = wide && graph !== null && graph.nodes.length > 0;

  const picker = (
    <PresetPicker
      choice={choice}
      caps={caps}
      custom={custom}
      disabled={busy}
      onChoice={(next) => remember(next, null)}
      onOpenDrawer={() => setDrawerOpen(true)}
    />
  );

  const composer = (
    <ChatInput
      value={input}
      onChange={setInput}
      onSend={() => send()}
      onStop={conversation.stop}
      busy={busy}
      disabled={quotaExhausted}
      placeholder={
        quotaExhausted
          ? "Free chat allowance used up."
          : `Ask anything about ${repoName}`
      }
      picker={picker}
    />
  );

  return (
    <div
      className="fixed inset-x-0 top-26.5 bottom-0 overflow-hidden bg-[radial-gradient(ellipse_at_50%_40%,#0092b814,transparent_60%),#060608] md:top-16.25"
      data-testid="chat-page"
    >
      {/* Breakpoints, not the media-query hook, pick between the panel and the
          drawer: the hook reads false until hydration, which would flash the
          narrow layout on a wide screen. */}
      <div className="absolute inset-y-0 left-0 z-30 hidden w-65 md:block">
        <ConversationSidebar
          items={list.items}
          loaded={list.loaded}
          activeId={conversation.activeId}
          drawer={false}
          open
          onClose={() => {}}
          onSelect={openConversation}
          onNew={() => openConversation(null)}
          onRename={list.rename}
          onDelete={deleteConversation}
        />
      </div>
      <div className="md:hidden">
        <button
          type="button"
          aria-label="Open conversations"
          onClick={() => setSidebarOpen(true)}
          className="ghost absolute top-3 left-3 z-20 flex items-center gap-1.5 rounded-sm border border-(--border) bg-(--card) px-3 py-1.5 font-pixel text-xs tracking-[0.06em] text-zinc-300 uppercase cursor-pointer"
        >
          <span aria-hidden="true">≡</span>
          Chats
        </button>
        <ConversationSidebar
          items={list.items}
          loaded={list.loaded}
          activeId={conversation.activeId}
          drawer
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          onSelect={openConversation}
          onNew={() => openConversation(null)}
          onRename={list.rename}
          onDelete={deleteConversation}
        />
      </div>
      <div className="absolute inset-y-0 right-0 left-0 md:left-65">
        {showGraph && (
          <div className="absolute inset-0 opacity-85" data-testid="graph-layer">
            <LiveGraph
              graph={graph}
              highlight={focusState.highlight}
              laneColors={laneColors}
              live={busy}
              pulsePath={pulsePath}
            />
          </div>
        )}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-[linear-gradient(90deg,#060608_0%,#060608cc_22%,#06060866_50%,#060608cc_78%,#060608_100%)]"
        />

        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="absolute inset-0 overflow-y-auto custom-scrollbar"
          data-testid="message-scroll"
        >
          <div
            ref={columnRef}
            className="mx-auto flex w-full max-w-190 flex-col gap-7 px-4 pt-14 pb-56 md:px-6 md:pt-8"
          >
            {turns.map((turn) => (
              <TurnView
                key={turn.id}
                turn={turn}
                repo={repoRef}
                repoId={repoId}
                onReask={busy ? undefined : (question) => send(question)}
                onDelete={conversation.remove}
                onPulse={setPulsePath}
              />
            ))}
          </div>
        </div>

        <AnimatePresence>
          {!atBottom && !empty && (
            <motion.button
              type="button"
              onClick={jumpToLatest}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 8 }}
              className="ghost absolute bottom-36 left-1/2 z-20 flex -translate-x-1/2 items-center gap-1.5 rounded-sm border border-(--border) bg-(--card) px-3 py-1.5 font-pixel text-xs tracking-[0.06em] text-zinc-300 uppercase shadow-lg cursor-pointer"
            >
              <span aria-hidden="true">↓</span>
              Jump to latest
            </motion.button>
          )}
        </AnimatePresence>

        <div
          className={`pointer-events-none absolute inset-0 z-10 flex flex-col items-center px-4 pb-6 md:px-6 ${empty ? "justify-center" : "justify-end bg-[linear-gradient(transparent_calc(100%-220px),#060608_calc(100%-110px))]"}`}
        >
          <motion.div
            layout={!reduced}
            transition={{ type: "spring", stiffness: 160, damping: 24 }}
            className="pointer-events-auto flex w-full max-w-190 flex-col gap-2.5"
          >
            {/* Until the history arrives the thread is assumed empty, so the
              composer holds the centre the route skeleton put it in rather
              than dropping to the bottom and coming back. */}
            {!loaded && <GreetingSkeleton />}
            <AnimatePresence>
              {empty && loaded && (
                <motion.div
                  key="greeting"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8, height: 0 }}
                  transition={{ duration: 0.25 }}
                  className="mb-2 text-center"
                >
                  <p
                    aria-hidden="true"
                    className="m-0 mb-3 font-pixel text-[13px] tracking-[0.08em] text-(--subtle-foreground)"
                  >
                    <span className="text-(--accent)">&gt;</span> illume ask
                    <span className="caret">_</span>
                  </p>
                  <h1 className="m-0 text-3xl font-medium tracking-tight">
                    What would you like to know about{" "}
                    <span className="font-pixel text-(--accent)">{repoName}</span>?
                  </h1>
                </motion.div>
              )}
            </AnimatePresence>

            {quotaExhausted && (
              <div className="flex items-center gap-2 rounded-sm border border-(--accent)/25 bg-(--accent)/5 px-3 py-2 text-xs text-(--muted-foreground)">
                <span aria-hidden="true" className="font-pixel text-(--accent)">
                  !
                </span>
                <span>
                  You&apos;ve used up the free chat questions.{" "}
                  <Link
                    href="/settings"
                    className="text-(--accent) underline-offset-2 hover:underline"
                  >
                    Add your own API key
                  </Link>{" "}
                  to keep chatting.
                </span>
              </div>
            )}

            {(branch || commitSha) && !empty && (
              <p className="m-0 font-pixel text-[11px] tracking-[0.08em] text-(--faint-foreground) uppercase">
                Answers come from{" "}
                <span className="normal-case">
                  {branch ?? "detached"}
                  {commitSha && ` @ ${commitSha.slice(0, 7)}`}
                </span>
              </p>
            )}

            {composer}

            {!loaded && <SuggestionsSkeleton />}
            <AnimatePresence>
              {empty && loaded && (
                <motion.ul
                  key="suggestions"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0, height: 0 }}
                  className="grid gap-2 sm:grid-cols-3"
                  aria-label="Suggested questions"
                >
                  {suggestions.map((question) => (
                    <li key={question}>
                      <button
                        type="button"
                        disabled={quotaExhausted}
                        onClick={() => send(question)}
                        className="ghost h-full w-full rounded-sm border border-(--border) bg-(--card) p-3 text-left text-[13px] leading-snug text-(--muted-foreground) disabled:opacity-50 cursor-pointer"
                      >
                        {question}
                      </button>
                    </li>
                  ))}
                </motion.ul>
              )}
            </AnimatePresence>

            {remaining !== null && !quotaExhausted && (
              <p className="m-0 text-center font-pixel text-[11px] tracking-[0.06em] text-(--subtle-foreground) uppercase">
                {remaining} free {remaining === 1 ? "question" : "questions"}{" "}
                left
              </p>
            )}
          </motion.div>
        </div>

        <AdvancedDrawer
          open={drawerOpen}
          preset={preset}
          settings={effective}
          caps={caps}
          onClose={() => setDrawerOpen(false)}
          onPreset={(next) => remember(next, null)}
          onChange={(next) =>
            remember(choice === "auto" ? preset : choice, next)
          }
        />
      </div>
    </div>
  );
}
