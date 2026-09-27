/**
 * Repository-scoped chat panel with history and streaming input.
 * @module Chat
 */
"use client";

import { useChat } from "@/hooks/useChat";
import { TrashIcon } from "@phosphor-icons/react";
import { RobotIcon, SparkleIcon } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";
import { useState } from "react";
import Button from "./ui/Button";
import ChatBubble from "./ui/ChatBubble";
import Textarea from "./ui/Textarea";

/**
 * Displays codebase Q&A history with a composer for new questions.
 *
 * @param repoId - ID of the repository whose chat history to show.
 * @param url - Repository URL forwarded to message bubbles for links.
 * @param branch - Repository's ingested branch, forwarded to citation links.
 * @param freeChatRemaining - Free-tier chat messages left for the user.
 *                            `null` means the count is unknown (e.g. the
 *                            user has a BYOK key, where the quota does not
 *                            apply). At zero the composer is disabled with
 *                            a note pointing to /settings, mirroring the
 *                            server-side 402.
 * @returns Chat panel with history, empty state, and input row.
 */
export default function Chat({
  repoId,
  url,
  branch,
  freeChatRemaining,
}: {
  repoId: string;
  url: string;
  branch?: string | null;
  freeChatRemaining: number | null;
}) {
  const { messages, isLoading, sendMessage, deleteMessage, clearHistory } =
    useChat({
      repoId,
    });
  const [input, setInput] = useState("");

  /**
   * Composer is disabled when there is nothing to send OR when the user has
   * burned the free allowance and has no key. The flag is derived once and
   * drives both the textarea and the send button so a user cannot bypass the
   * gate by, e.g., pressing Enter.
   */
  const quotaExhausted = freeChatRemaining !== null && freeChatRemaining <= 0;
  const canSend = !isLoading && input.trim().length > 0 && !quotaExhausted;

  /** Sends the trimmed composer text and clears the input. */
  const handleSend = () => {
    if (!canSend) return;
    sendMessage(input.trim());
    setInput("");
  };

  /** Submits on Enter while preserving Shift+Enter newlines. */
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="w-full h-full flex flex-col">
      <div className="flex items-center justify-between p-4 shrink-0 border-b bg-(--background)/50">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-(--primary) shadow-[0_0_8px_var(--primary)] animate-pulse" />
          Chat with Codebase
        </h2>
        <div className="flex items-center gap-3">
          {freeChatRemaining !== null && (
            <span
              className="inline-flex items-center gap-1.5 text-xs text-(--muted-foreground)"
              title="Free chat questions remaining on the server key"
            >
              <SparkleIcon size={12} weight="duotone" />
              {freeChatRemaining} free{" "}
              {freeChatRemaining === 1 ? "question" : "questions"} left
            </span>
          )}
          {messages.length > 0 && (
            <button
              onClick={clearHistory}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-(--muted-foreground) hover:text-red-400 hover:bg-red-500/10 border border-transparent hover:border-red-500/20 rounded-lg transition duration-200 cursor-pointer"
              title="Clear Chat History"
            >
              <TrashIcon size={14} weight="bold" />
              Clear Chat
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto flex flex-col gap-4 p-4 min-h-0 custom-scrollbar">
        {messages.length === 0 && (
          <div className="flex-1 flex flex-col items-center justify-center text-center opacity-50 space-y-2">
            <RobotIcon size={48} weight="thin" />
            <p className="text-sm max-w-50">
              Ask questions about the architecture, logic, or ownership.
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <ChatBubble
            key={msg.id}
            id={msg.id}
            question={msg.question}
            message={msg.answer}
            error={msg.error}
            errorKind={msg.errorKind}
            url={url}
            branch={branch}
            onDelete={deleteMessage}
          />
        ))}
      </div>

      {quotaExhausted && (
        <div className="mx-2 mb-2 px-3 py-2 text-xs text-(--muted-foreground) border border-(--primary)/20 rounded bg-(--primary)/5 flex items-center gap-1.5">
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

      <div className="relative m-2">
        <Textarea
          className="w-full"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            quotaExhausted
              ? "Free chat allowance used up."
              : "Ask about the codebase…"
          }
          rows={2}
          disabled={quotaExhausted}
        />

        <Button
          onClick={handleSend}
          loading={isLoading}
          disabled={!canSend}
          size="sm"
          className="absolute bottom-2.5 right-2.5"
        >
          {isLoading ? "Thinking..." : "Send"}
        </Button>
      </div>
    </div>
  );
}
