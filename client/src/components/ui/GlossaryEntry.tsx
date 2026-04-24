import { GithubLogoIcon } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

export default function GlossaryEntry({
  entry,
  start,
  idx,
  github_url,
}: {
  entry: any;
  start: number;
  idx: number;
  github_url: string;
}) {
  return (
    <div
      key={entry.id}
      className="glass-card p-4 hover:border-(--chart-2)/40 transition-colors group"
    >
      <div className="flex items-center justify-between gap-4 mb-3 mt-1">
        <div className="flex items-center gap-3">
          <span className="font-mono text-sm text-(--muted-foreground) w-6 text-right shrink-0">
            {String(start + idx).padStart(2, "0")}
          </span>
          <h3 className="text-lg font-bold text-(--foreground) leading-none">
            {entry.name}
          </h3>
        </div>
        {entry.file_path && (
          <Link
            href={`${github_url}/blob/master/${entry.file_path}#L${entry.line_number}`}
            target="_blank"
            className="flex items-center gap-2 font-mono text-sm text-(--chart-2) bg-(--chart-2)/10 hover:bg-(--chart-2)/20 transition-colors px-2 py-1 rounded truncate max-w-50 sm:max-w-xs shrink-0"
            title={entry.file_path}
          >
            <GithubLogoIcon size={14} weight="fill" />
            {entry.file_path.split("/").pop()}
          </Link>
        )}
      </div>
      <div className="pl-9">
        <p className="text-(--muted-foreground) text-sm leading-relaxed whitespace-pre-wrap">
          {entry.definition}
        </p>
        {entry.line_number && (
          <div className="mt-3 text-[10px] font-mono text-(--muted-foreground)/60">
            Line: {entry.line_number}
          </div>
        )}
      </div>
    </div>
  );
}
