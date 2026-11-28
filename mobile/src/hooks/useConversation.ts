/**
 * One conversation's thread: its stored turns plus the live run.
 *
 * @module UseConversation
 *
 * Port of ``client/src/hooks/useConversation.ts``.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  deleteChatTurn,
  getConversationMessages,
  listAgentRuns,
  type StaleInfo,
} from "@/api/conversations";
import { stripMarks } from "@/lib/agent/answer";
import { boundHistory } from "@/lib/agent/limits";
import type { Overrides, PresetChoice } from "@/lib/agent/presets";
import {
  initialRunState,
  settledRunState,
  type RunState,
} from "@/lib/agent/reducer";
import type { Usage } from "@/lib/agent/types";
import { ApiError } from "@/lib/apiError";
import { useAgentStream, type HistoryMessage } from "./useAgentStream";
import type { StreamOptions } from "@/api/agentStream";

/** One question and the run that answered it. */
export interface Turn {
  id: string;
  question: string;
  /** The run to show: the stream state while this turn is in focus. */
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

/** What the screen wants to hear about as the thread changes. */
export interface ConversationCallbacks {
  /** A turn was saved; `created` is true when it started the conversation. */
  onTurnSaved?: (conversationId: string, created: boolean) => void;
  /** The selected conversation does not exist, or is not the caller's. */
  onMissing?: () => void;
}

let turnCounter = 0;

/** A local id for a turn that has no server record yet. */
function newTurnId(): string {
  turnCounter += 1;
  return `turn-${Date.now().toString(36)}-${turnCounter}`;
}

/**
 * Loads one conversation's stored turns and drives new runs on top of them.
 *
 * With no conversation selected the thread is empty, and the first question
 * starts a conversation on the server: when its answer is saved the new id
 * is adopted without reloading, so the streamed answer stays on screen.
 *
 * @param repoId - Repository UUID; empty until the repository has loaded.
 * @param initialConversationId - The conversation to open, or null for a new chat.
 * @param callbacks - Notifications for the screen.
 * @param transport - Test seams for the stream request.
 * @returns Turns, loading flag, the active conversation and the actions.
 */
export function useConversation(
  repoId: string,
  initialConversationId: string | null = null,
  callbacks: ConversationCallbacks = {},
  transport: StreamOptions = {},
) {
  const stream = useAgentStream(transport);
  const { start, reset } = stream;
  const [stored, setStored] = useState<StoredTurn[]>([]);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(
    initialConversationId,
  );
  const [loaded, setLoaded] = useState(initialConversationId === null);
  const activeIdRef = useRef(activeId);
  // An id adopted from a finished run: its turns are already on screen.
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
    if (!repoId) return;
    let cancelled = false;
    setLoaded(false);
    const load = async () => {
      try {
        const [rows, runs] = await Promise.all([
          getConversationMessages(repoId, activeId, transport),
          listAgentRuns(repoId, transport).catch(() => []),
        ]);
        if (cancelled) return;
        // What each answer's run spent, so stored turns show it as live ones do.
        const usageByMessage = new Map<string, Usage>();
        for (const run of runs) {
          if (!run.chat_message_id) continue;
          usageByMessage.set(run.chat_message_id, {
            input_tokens: run.input_tokens ?? undefined,
            output_tokens: run.output_tokens ?? undefined,
            tool_calls: run.tool_calls ?? undefined,
            elapsed_seconds:
              run.latency_ms != null ? run.latency_ms / 1000 : undefined,
          });
        }
        setStored(
          rows.map((row) => ({
            id: row.id,
            question: row.question,
            run: settledRunState(
              row.answer,
              row.sources ?? [],
              usageByMessage.get(row.id) ?? null,
            ),
            chatMessageId: row.id,
            stale: row.stale_at ? { paths: row.stale_paths ?? [] } : null,
          })),
        );
      } catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 404) {
          callbacksRef.current.onMissing?.();
        }
      } finally {
        if (!cancelled) setLoaded(true);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
    // The transport is a test seam and never changes in the app.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId, activeId]);

  // A saved answer names its conversation: adopt it when the thread had none,
  // and tell the screen so it can refresh the list.
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

  /** Copies the stream state onto the turn it was driving. */
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
      if (liveRef.current || !repoId) return;
      const frozen = freeze(storedRef.current);
      const history: HistoryMessage[] = frozen
        .filter((turn) => turn.run.status === "done" && turn.run.answer)
        .flatMap((turn) => [
          { role: "user" as const, content: turn.question },
          { role: "assistant" as const, content: stripMarks(turn.run.answer) },
        ]);
      const id = newTurnId();
      setStored([
        ...frozen,
        { id, question, run: initialRunState, chatMessageId: null },
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
        await deleteChatTurn(repoId, messageId, transport);
      } catch {
        // The turn is already gone from the screen; the server copy is
        // removed on the next successful delete or by clearing the thread.
      }
    },
    // The transport is a test seam and never changes in the app.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
