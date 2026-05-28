import ChatMessage from "@/types/chat";
import { BookBookmarkIcon, TrashIcon } from "@phosphor-icons/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import CitationCard from "./CitationCard";

interface Props {
  id: string;
  question: string;
  message: ChatMessage | null;
  error?: boolean;
  url: string;
  onDelete?: (id: string) => void;
}

export default function ChatBubble({
  id,
  question,
  message,
  error,
  url,
  onDelete,
}: Props) {
  return (
    <div className="flex flex-col gap-4 animate-fade-up group relative">
      <div className="self-end max-w-[85%]">
        <div className="border bg-(--card)/70 rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm text-white shadow-md">
          {question}
        </div>
      </div>

      <div className="self-start w-full max-w-[90%] flex flex-col gap-3 relative">
        {message === null ? (
          <div className="flex items-center gap-2 text-sm text-(--primary) font-medium p-2 animate-pulse">
            Analyzing codebase...
          </div>
        ) : (
          <div
            className={`bg-(--card)/70 rounded-2xl rounded-tl-sm p-5 shadow-sm border relative ${error ? "border-red-500/30 bg-red-950/10" : "border-(--border)"}`}
          >
            {onDelete && (
              <button
                onClick={() => onDelete(id)}
                className="absolute top-4 right-4 p-1.5 rounded-lg text-(--muted-foreground) hover:text-red-400 hover:bg-red-500/10 opacity-0 group-hover:opacity-100 transition-all duration-200 cursor-pointer"
                title="Delete message"
              >
                <TrashIcon size={16} />
              </button>
            )}

            <div
              className={`prose prose-sm dark:prose-invert max-w-none ${error ? "text-red-400 font-medium" : "text-(--foreground)"}`}
            >
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
                <div className="grid grid-cols-2 gap-2">
                  {message.sources.map((src, i) => (
                    <CitationCard url={url} key={i} src={src} />
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
