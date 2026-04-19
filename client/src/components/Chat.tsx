"use client";

import { useChat } from "@/hooks/useChat";
import { useEffect, useRef, useState } from "react";
import Button from "./ui/Button";
import ChatBubble from "./ui/ChatBubble";
import Textarea from "./ui/Textarea";

export default function Chat({ repoId }: { repoId: string }) {
  const { messages, isLoading, sendMessage } = useChat({
    repoId,
  });
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

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
    <section className="w-1/2 h-full backdrop-blur-xs border rounded-sm p-4 bg-black/30 flex flex-col">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-2xl font-semibold">Ask Anything</h2>
      </div>

      <div className="flex-1 overflow-y-auto flex flex-col gap-6 py-2 pr-1 min-h-0">
        {messages.map((msg, i) => (
          <ChatBubble key={i} question={msg.question} message={msg.answer} />
        ))}

        <div ref={bottomRef} />
      </div>

      <div className="relative">
        <Textarea
          className="w-full resize-none pb-12"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about the codebase… (Enter to send)"
          rows={2}
        />

        <Button
          onClick={handleSend}
          loading={isLoading}
          disabled={isLoading || !input.trim()}
          size="sm"
          className="absolute bottom-2 right-2"
        >
          Send
        </Button>
      </div>
    </section>
  );
}
