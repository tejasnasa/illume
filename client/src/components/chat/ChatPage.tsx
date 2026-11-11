/**
 * The fullscreen chat: live graph, message column and floating input.
 * @module ChatPage
 */
"use client";

import { useConversation } from "@/hooks/useConversation";
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
import {
  ArrowDownIcon,
  DotsThreeIcon,
  SparkleIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AdvancedDrawer from "./AdvancedDrawer";
import ChatInput from "./ChatInput";
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
}: ChatPageProps) {
  const reduced = useReducedMotion();
  const wide = useMediaQuery("(min-width: 768px)");
  const graph = useRepoGraph();
  const conversation = useConversation(repoId);
  const { turns, busy, focusState, loaded } = conversation;

  const [input, setInput] = useState("");
  const [choice, setChoice] = useState<PresetChoice>(() =>
    defaultPreset(caps),
  );
  const [settings, setSettings] = useState<DrawerSettings | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
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
    el.scrollTo({ top: el.scrollHeight, behavior: reduced ? "auto" : "smooth" });
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
        quotaExhausted ? "Free chat allowance used up." : "Ask about the codebase…"
      }
      picker={picker}
    />
  );

  return (
    <div
      className="fixed inset-x-0 bottom-0 top-16 overflow-hidden"
      data-testid="chat-page"
    >
      {showGraph && (
        <div className="absolute inset-0 -top-16" data-testid="graph-layer">
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
        className="pointer-events-none absolute inset-0 bg-linear-to-b from-(--background)/50 via-transparent to-(--background)/80"
      />

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="absolute inset-0 overflow-y-auto custom-scrollbar"
        data-testid="message-scroll"
      >
        <div
          ref={columnRef}
          className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 pb-52 pt-4"
        >
          {!empty && (
            <div className="flex justify-end">
              <div className="relative">
                <button
                  type="button"
                  aria-label="Chat options"
                  aria-haspopup="menu"
                  aria-expanded={menuOpen}
                  onClick={() => setMenuOpen((v) => !v)}
                  className="rounded-lg p-1.5 text-(--muted-foreground) hover:bg-(--secondary)/50 cursor-pointer"
                >
                  <DotsThreeIcon size={20} weight="bold" />
                </button>
                {menuOpen && (
                  <div
                    role="menu"
                    className="absolute right-0 z-20 mt-1 w-44 rounded-lg border border-(--border) bg-(--card) p-1 shadow-xl"
                  >
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setMenuOpen(false);
                        void conversation.clear();
                      }}
                      className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-xs text-(--destructive) hover:bg-(--destructive)/10 cursor-pointer"
                    >
                      <TrashIcon size={14} />
                      Clear chat history
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

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
            className="absolute bottom-32 left-1/2 z-20 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-(--border) bg-(--card)/90 px-3 py-1.5 text-xs text-(--foreground) shadow-lg backdrop-blur-md cursor-pointer"
          >
            <ArrowDownIcon size={12} weight="bold" />
            Jump to latest
          </motion.button>
        )}
      </AnimatePresence>

      <div
        className={`pointer-events-none absolute inset-0 z-10 flex flex-col items-center px-4 pb-4 ${empty ? "justify-center" : "justify-end"}`}
      >
        <motion.div
          layout={!reduced}
          transition={{ type: "spring", stiffness: 160, damping: 24 }}
          className="pointer-events-auto flex w-full max-w-3xl flex-col gap-3"
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
                <SparkleIcon
                  size={22}
                  weight="duotone"
                  className="mx-auto mb-3 text-(--chart-1)"
                />
                <h1 className="text-2xl font-semibold tracking-tight">
                  What would you like to know about {repoName}?
                </h1>
              </motion.div>
            )}
          </AnimatePresence>

          {quotaExhausted && (
            <div className="flex items-center gap-1.5 rounded border border-(--primary)/20 bg-(--primary)/5 px-3 py-2 text-xs text-(--muted-foreground)">
              <SparkleIcon size={12} weight="duotone" />
              <span>
                You&apos;ve used up the free chat questions.{" "}
                <Link
                  href="/settings"
                  className="text-(--primary) underline-offset-2 hover:underline"
                >
                  Add your own API key
                </Link>{" "}
                to keep chatting.
              </span>
            </div>
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
                      className="h-full w-full rounded-xl border border-(--border) bg-(--card)/40 p-3 text-left text-xs text-(--muted-foreground) backdrop-blur-md transition-colors hover:border-(--primary)/40 hover:text-(--foreground) disabled:opacity-50 cursor-pointer"
                    >
                      {question}
                    </button>
                  </li>
                ))}
              </motion.ul>
            )}
          </AnimatePresence>

          {remaining !== null && !quotaExhausted && (
            <p className="text-center text-[11px] text-(--muted-foreground)">
              {remaining} free {remaining === 1 ? "question" : "questions"} left
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
        onChange={(next) => remember(choice === "auto" ? preset : choice, next)}
      />
    </div>
  );
}
