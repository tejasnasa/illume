"use client";

import Repository from "@/types/repository";
import { timeAgo } from "@/utils/timeAgo";
import {
  ArrowRightIcon,
  CheckCircleIcon,
  CircleDashedIcon,
  ClockIcon,
  GithubLogoIcon,
  SparkleIcon,
  WarningIcon,
} from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

export default function RepoCard({ repo }: { repo: Repository }) {
  const isReady = repo.status === "ready";
  const isFailed = repo.status === "failed";
  const isPending = !isReady && !isFailed;

  return (
    <Link
      href={`/repo/${repo.repo_number}`}
      className="group relative glass-card rounded-sm p-6 block hover:border-(--primary)/50 transition-all duration-300 hover:shadow-xl hover:shadow-(--primary)/5"
    >
      <div
        className="absolute top-4 right-4 flex items-center gap-1 z-10"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
      >
        <a
          href={repo.github_url}
          target="_blank"
          className="p-2 rounded-sm text-(--muted-foreground) hover:text-(--foreground) hover:bg-(--secondary) transition-colors"
          title="Open GitHub"
          onClick={(e) => {
            e.stopPropagation();
          }}
        >
          <GithubLogoIcon size={20} />
        </a>
        <div className="p-2 text-(--muted-foreground) group-hover:text-(--primary) group-hover:translate-x-1 transition-all">
          <ArrowRightIcon size={20} weight="bold" />
        </div>
      </div>

      <div className="flex items-start gap-4 mb-6">
        <div className="p-3 rounded-xl bg-(--secondary) text-(--primary) group-hover:bg-(--primary)/10 transition-colors">
          <SparkleIcon size={28} weight="fill" />
        </div>
        <div className="min-w-0">
          <h3 className="text-xl font-bold truncate pr-12 group-hover:text-(--primary) transition-colors">
            {repo.name}
          </h3>
          <div className="flex items-center gap-2 mt-1">
            <span
              className={`flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full ${
                isReady
                  ? "bg-green-500/10 text-green-500"
                  : isFailed
                    ? "bg-red-500/10 text-red-500"
                    : "bg-yellow-500/10 text-yellow-500"
              }`}
            >
              {isReady && <CheckCircleIcon size={12} weight="fill" />}
              {isFailed && <WarningIcon size={12} weight="fill" />}
              {isPending && (
                <CircleDashedIcon size={12} className="animate-spin" />
              )}
              {repo.status}
            </span>
            <span className="text-[10px] text-(--muted-foreground) flex items-center gap-1">
              <ClockIcon size={12} />
              {timeAgo(repo.updated_at)}
            </span>
          </div>
        </div>
      </div>

      {repo.architecture_summary ? (
        <p className="text-sm text-(--muted-foreground) line-clamp-4 leading-relaxed mb-4">
          {repo.architecture_summary}
        </p>
      ) : (
        <div className="h-20 flex items-center justify-center border-2 border-dashed border-(--border) rounded-xl mb-4 bg-(--secondary)/5">
          <span className="text-xs text-(--muted-foreground) italic">
            Waiting for AI analysis...
          </span>
        </div>
      )}

      <div className="flex items-center gap-4 w-full">
        <div className="flex flex-col w-full">
          <div className="flex gap-1 mt-1 overflow-x-hidden w-full">
            {(() => {
              const langs = repo.detected_stack?.languages ?? [];
              const frameworks = repo.detected_stack?.frameworks ?? [];
              const all = [...langs, ...frameworks];

              return all.length > 0 ? (
                all.map((item: string, i: number) => (
                  <span
                    key={i}
                    className="px-1.5 py-0.5 rounded bg-(--secondary) text-(--foreground) text-xs font-mono border border-(--border) whitespace-nowrap shrink-0"
                  >
                    {item}
                  </span>
                ))
              ) : (
                <span className="text-[9px] text-(--muted-foreground)/50 italic">
                  Detecting...
                </span>
              );
            })()}
          </div>
        </div>
      </div>
    </Link>
  );
}
