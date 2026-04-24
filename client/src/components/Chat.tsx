"use client";

import { useChat } from "@/hooks/useChat";
import { RobotIcon } from "@phosphor-icons/react/dist/ssr";
import { useState } from "react";
import Button from "./ui/Button";
import ChatBubble from "./ui/ChatBubble";
import Textarea from "./ui/Textarea";

export default function Chat({ repoId, url }: { repoId: string; url: string }) {
  const { messages, isLoading, sendMessage } = useChat({
    repoId,
  });
  const [input, setInput] = useState("");

  const handleSend = () => {
    if (!input.trim()) return;
    sendMessage(input.trim());
    setInput("");
  };

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

        {messages.map((msg, i) => (
          <ChatBubble key={i} question={msg.question} message={msg.answer} url={url} />
        ))}
      </div>

      <div className="relative m-2">
        <Textarea
          className="w-full"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about the codebase…"
          rows={2}
        />

        <Button
          onClick={handleSend}
          loading={isLoading}
          disabled={isLoading || !input.trim()}
          size="sm"
          className="absolute bottom-2.5 right-2.5"
        >
          {isLoading ? "Thinking..." : "Send"}
        </Button>
      </div>
    </div>
  );
}
