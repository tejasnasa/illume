"use client";

import ChatMessage from "@/types/chat";
import { useState } from "react";
import Textarea from "./ui/Textarea";

export default function Chat() {
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  
  return (
    <section className="w-1/2 h-full backdrop-blur-xs border rounded-sm p-4 bg-black/30 ">
      <h2 className="text-2xl font-semibold mb-2">Ask Anything</h2>
      <div></div>
      <Textarea className="w-full" />
    </section>
  );
}
