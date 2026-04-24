import ChatMessage from "@/types/chat";
import { BookBookmarkIcon } from "@phosphor-icons/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import CitationCard from "./CitationCard";

interface Props {
  question: string;
  message: ChatMessage | null;
  url: string;
}

export default function ChatBubble({ question, message, url }: Props) {
  return (
    <div className="flex flex-col gap-4 animate-fade-up">
      <div className="self-end max-w-[85%]">
        <div className="border bg-(--card)/70 rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm text-white shadow-md">
          {question}
        </div>
      </div>

      <div className="self-start w-full max-w-[90%] flex flex-col gap-3">
        {message === null ? (
          <div className="flex items-center gap-2 text-sm text-(--primary) font-medium p-2 animate-pulse">
            Analyzing codebase...
          </div>
        ) : (
          <div className="bg-(--card)/70 rounded-2xl rounded-tl-sm p-5 shadow-sm border border-(--border)">
            <div className="prose prose-sm dark:prose-invert max-w-none text-(--foreground)">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.answer}
              </ReactMarkdown>
            </div>

            {message.sources && message.sources.length > 0 && (
              <div className="mt-6 pt-4 border-t border-(--border)/50">
                <div className="flex items-center gap-2 mb-3 text-xs font-semibold uppercase tracking-widest text-(--muted-foreground)">
                  <BookBookmarkIcon size={14} />
                  Sources Cited ({message.sources.length})
                </div>
                <div className="grid grid-cols-1 gap-2">
                  {message.sources.map((src, i) => (
                    <CitationCard url={url} key={i} src={src} index={i} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
