/**
 * One conversation's thread: its stored turns plus the live run.
 * @module UseConversation
 */
"use client";

import { stripMarks } from "@/lib/agent/answer";
import { boundHistory } from "@/lib/agent/limits";
import type { Overrides, PresetChoice } from "@/lib/agent/presets";
import {
  initialRunState,
  settledRunState,
  type RunState,
} from "@/lib/agent/reducer";
import type { AgentRunSummary, Citation, Usage } from "@/lib/agent/types";
import type { StaleInfo } from "@/components/chat/StaleNotice";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAgentStream, type HistoryMessage } from "./useAgentStream";

/** One question and the run that answered it. */
export interface Turn {
  id: string;
  question: string;
  /** The run to show: the stream's state while this turn is in focus. */
  run: RunState;
  chatMessageId: string | null;
  /** True while the stream is driving this turn's run. */
  inFocus: boolean;
  /** Set when files the answer cited have changed since it was given. */
  stale: StaleInfo | null;
}

interface StoredTurn {
  id: string;
  question: string;
  run: RunState;
  chatMessageId: string | null;
  stale?: StaleInfo | null;
}

interface HistoryRow {
  id: string;
  question: string;
  answer: string;
  sources: Partial<Citation>[] | null;
  stale_at?: string | null;
  stale_paths?: string[] | null;
}

const BACKEND = () => process.env.NEXT_PUBLIC_BACKEND_URL;

/** What the page wants to hear about as the thread changes. */
export interface ConversationCallbacks {
  /** A turn was saved; `created` is true when it started the conversation. */
  onTurnSaved?: (conversationId: string, created: boolean) => void;
  /** The selected conversation does not exist, or is not the caller's. */
  onMissing?: () => void;
}

/**
 * Loads one conversation's stored turns and drives new runs on top of them.
 *
 * With no conversation selected the thread is empty, and the first question
 * starts a conversation on the server: when its answer is saved the new id is
 * adopted without reloading, so the streamed answer stays on screen.
 *
 * One run is in focus at a time, the newest. Every other turn keeps the state
 * it settled in.
 *
 * @param repoId - Repository id.
 * @param initialConversationId - The conversation to open, or null for a new chat.
 * @param callbacks - Notifications for the page.
 * @returns Turns, loading flag, the active conversation and the actions the page offers.
 */
export function useConversation(
  repoId: string,
  initialConversationId: string | null = null,
  callbacks: ConversationCallbacks = {},
) {
  const stream = useAgentStream();
  const { start, reset } = stream;
  const [stored, setStored] = useState<StoredTurn[]>([]);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(
    initialConversationId,
  );
  const [loaded, setLoaded] = useState(initialConversationId === null);
  const activeIdRef = useRef(activeId);
  // An id the hook adopted from a finished run: its turns are already on screen.
  const adoptedRef = useRef<string | null>(null);
  const notifiedRunRef = useRef<string | null>(null);
  const callbacksRef = useRef(callbacks);
  callbacksRef.current = callbacks;
  activeIdRef.current = activeId;
  const storedRef = useRef(stored);
  const focusRef = useRef(focusId);
  const streamStateRef = useRef(stream.state);
  const liveRef = useRef(stream.isLive);
  storedRef.current = stored;
  focusRef.current = focusId;
  streamStateRef.current = stream.state;
  liveRef.current = stream.isLive;

  useEffect(() => {
    if (activeId === null) {
      setLoaded(true);
      return;
    }
    if (adoptedRef.current === activeId) {
      adoptedRef.current = null;
      setLoaded(true);
      return;
    }
    let cancelled = false;
    setLoaded(false);
    const load = async () => {
      try {
        const base = `${BACKEND()}/api/v1/repository/${repoId}`;
        const [history, runs] = await Promise.all([
          fetch(`${base}/conversations/${activeId}/messages`, {
            credentials: "include",
          }),
          fetch(`${base}/agent-runs?limit=100`, {
            credentials: "include",
          }).catch(() => null),
        ]);
        if (cancelled) return;
        if (history.status === 404) {
          callbacksRef.current.onMissing?.();
          return;
        }
        if (!history.ok) return;
        const rows = (await history.json()) as HistoryRow[];
        // What each answer's run spent, so stored turns show it as live ones do.
        const usageByMessage = new Map<string, Usage>();
        if (runs?.ok) {
          for (const run of (await runs.json()) as AgentRunSummary[]) {
            if (!run.chat_message_id) continue;
            usageByMessage.set(run.chat_message_id, {
              input_tokens: run.input_tokens ?? undefined,
              output_tokens: run.output_tokens ?? undefined,
              tool_calls: run.tool_calls ?? undefined,
              elapsed_seconds:
                run.latency_ms != null ? run.latency_ms / 1000 : undefined,
            });
          }
        }
        if (cancelled) return;
        const mapped: StoredTurn[] = rows.map((row) => ({
          id: row.id,
          question: row.question,
          run: settledRunState(
            row.answer,
            row.sources ?? [],
            usageByMessage.get(row.id) ?? null,
          ),
          chatMessageId: row.id,
          stale: row.stale_at ? { paths: row.stale_paths ?? [] } : null,
        }));
        setStored(mapped);
      } catch (error) {
        console.error("Failed to fetch chat history", error);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [repoId, activeId]);

  // A saved answer names its conversation: adopt it when the thread had none,
  // and tell the page so it can refresh the list and the address.
  useEffect(() => {
    const state = stream.state;
    if (state.status !== "done" || !state.runId) return;
    if (notifiedRunRef.current === state.runId) return;
    notifiedRunRef.current = state.runId;
    const id = state.conversationId;
    if (!id) return;
    const created = activeIdRef.current === null;
    if (created) {
      adoptedRef.current = id;
      activeIdRef.current = id;
      setActiveId(id);
    }
    callbacksRef.current.onTurnSaved?.(id, created);
  }, [stream.state]);

  /** Copies the stream's state onto the turn it was driving. */
  const freeze = useCallback((turns: StoredTurn[]): StoredTurn[] => {
    const id = focusRef.current;
    if (!id) return turns;
    const state = streamStateRef.current;
    return turns.map((turn) =>
      turn.id === id
        ? {
            ...turn,
            run: state.status === "idle" ? turn.run : state,
            chatMessageId: state.chatMessageId ?? turn.chatMessageId,
          }
        : turn,
    );
  }, []);

  const turns: Turn[] = stored.map((turn) =>
    turn.id === focusId
      ? {
          ...turn,
          run: stream.state.status === "idle" ? turn.run : stream.state,
          chatMessageId: stream.state.chatMessageId ?? turn.chatMessageId,
          inFocus: true,
          stale: null,
        }
      : { ...turn, inFocus: false, stale: turn.stale ?? null },
  );

  const send = useCallback(
    (question: string, preset: PresetChoice, overrides?: Overrides) => {
      if (liveRef.current) return;
      const frozen = freeze(storedRef.current);
      const history: HistoryMessage[] = frozen
        .filter((turn) => turn.run.status === "done" && turn.run.answer)
        .flatMap((turn) => [
          { role: "user" as const, content: turn.question },
          { role: "assistant" as const, content: stripMarks(turn.run.answer) },
        ]);
      const id = crypto.randomUUID();
      setStored([
        ...frozen,
        {
          id,
          question,
          run: initialRunState,
          chatMessageId: null,
        },
      ]);
      setFocusId(id);
      focusRef.current = id;
      void start({
        repoId,
        question,
        preset,
        overrides,
        history: boundHistory(history),
        conversationId: activeIdRef.current,
      });
    },
    [repoId, freeze, start],
  );

  /** Deletes one turn here and on the server. */
  const remove = useCallback(
    async (turnId: string) => {
      const turn = storedRef.current.find((item) => item.id === turnId);
      const inFocus = focusRef.current === turnId;
      const messageId = inFocus
        ? (streamStateRef.current.chatMessageId ?? turn?.chatMessageId ?? null)
        : (turn?.chatMessageId ?? null);
      if (inFocus) {
        reset();
        setFocusId(null);
        focusRef.current = null;
      }
      setStored((current) => current.filter((item) => item.id !== turnId));
      if (!messageId) return;
      try {
        await fetch(
          `${BACKEND()}/api/v1/repository/${repoId}/chat/${messageId}`,
          { method: "DELETE", credentials: "include" },
        );
      } catch (error) {
        console.error("Failed to delete chat message on server", error);
      }
    },
    [repoId, reset],
  );

  /**
   * Opens a conversation, or an empty new chat when `id` is null.
   *
   * A live run is cancelled: its answer would otherwise land in a thread it
   * does not belong to.
   */
  const select = useCallback(
    (id: string | null) => {
      if (id === activeIdRef.current) return;
      reset();
      setFocusId(null);
      focusRef.current = null;
      setStored([]);
      adoptedRef.current = null;
      activeIdRef.current = id;
      setActiveId(id);
    },
    [reset],
  );

  return {
    turns,
    loaded,
    busy: stream.isLive,
    focusState: focusId ? stream.state : initialRunState,
    focusId,
    activeId,
    select,
    send,
    stop: stream.stop,
    remove,
  };
}
