import ChatMessage from "@/types/chat";
import {
  CircleNotchIcon,
  CodeIcon,
  FileIcon,
  GitCommitIcon,
  GitPullRequestIcon,
} from "@phosphor-icons/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  question: string;
  message: ChatMessage | null;
}

function SourceChip({ src }: { src: ChatMessage["sources"][number] }) {
  const type = (
    ["symbol", "commit", "pr"].includes(src.source_type)
      ? src.source_type
      : "file"
  ) as "symbol" | "commit" | "pr" | "file";

  const config = {
    symbol: {
      icon: CodeIcon,
      color: "text-(--chart-1)",
      bg: "bg-(--chart-1)/10",
      border: "border-(--chart-1)/20",
    },
    commit: {
      icon: GitCommitIcon,
      color: "text-(--primary)",
      bg: "bg-(--primary)/10",
      border: "border-(--primary)/20",
    },
    pr: {
      icon: GitPullRequestIcon,
      color: "text-(--chart-2)",
      bg: "bg-(--chart-2)/10",
      border: "border-(--chart-2)/20",
    },
    file: {
      icon: FileIcon,
      color: "text-(--muted-foreground)",
      bg: "bg-(--muted)/10",
      border: "border-(--border)",
    },
  }[type];

  const Icon = config.icon;

  return (
    <div
      className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded-md border ${config.bg} ${config.border}`}
    >
      <Icon size={12} className={`${config.color} shrink-0`} weight="bold" />
      <span className={`${config.color} font-medium`}>
        {type === "symbol" && src.symbol_name}
        {type === "commit" && src.author_name}
        {type === "pr" && `PR #${src.pr_number}`}
        {type === "file" && (src.file_path || "source")}
      </span>
      <span className="text-(--muted-foreground)">
        {type === "symbol" &&
          src.file_path &&
          `· ${src.file_path}${src.start_line ? `:${src.start_line}` : ""}`}
        {type === "commit" &&
          src.commit_hash &&
          `· ${src.commit_hash.slice(0, 7)}`}
        {type === "pr" && src.pr_title && `· ${src.pr_title}`}
        {type === "file" &&
          src.chunk_text &&
          `· ${src.chunk_text.slice(0, 50)}…`}
      </span>
    </div>
  );
}

export default function ChatBubble({ question, message }: Props) {
  return (
    <div className="flex flex-col gap-3">
      <div className="self-end max-w-[80%]">
        <div className="bg-(--secondary) border border-(--border) rounded-2xl rounded-tr-sm px-3.5 py-2 text-sm text-(--foreground)">
          {question}
        </div>
      </div>

      <div className="self-start max-w-[90%] flex flex-col gap-2.5">
        {message === null ? (
          <div className="flex items-center gap-2 text-sm text-(--muted-foreground)">
            <CircleNotchIcon
              size={14}
              className="animate-spin text-(--primary)"
              weight="bold"
            />
            Thinking…
          </div>
        ) : (
          <>
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.answer}
              </ReactMarkdown>
            </div>
            {message.sources?.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-0.5">
                {message.sources.map((src, i) => (
                  <SourceChip key={i} src={src} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
