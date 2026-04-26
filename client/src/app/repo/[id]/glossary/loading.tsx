import Skeleton from "@/components/ui/Skeleton";
import {
  BookOpenTextIcon,
  GithubLogoIcon,
  MagnifyingGlassIcon,
} from "@phosphor-icons/react/dist/ssr";

export default function GlossaryLoading() {
  return (
    <main className="max-w-5xl mx-auto p-6 pt-12 text-(--muted-foreground) overflow-hidden h-[calc(100vh-64px)]">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-10">
        <div className="flex-1 animate-pulse">
          <div>
            <div className="flex items-center gap-3 mb-2 ">
              <BookOpenTextIcon size={28} weight="duotone" />
              <h1 className="text-3xl font-bold  tracking-tight">
                Codebase Glossary
              </h1>
            </div>
            <p className="text-(--muted-foreground)">
              Domain terms, core classes, and functions explained in plain
              English.
            </p>
          </div>
        </div>
        <form className="relative w-full md:w-80 group">
          <MagnifyingGlassIcon
            size={18}
            className="absolute left-4 top-1/2 -translate-y-1/2 text-(--muted-foreground)/50 transition-colors"
          />
          <Skeleton className="w-full h-10 rounded-md" />
        </form>
      </div>
      <div className="flex justify-between items-center mb-6">
        <Skeleton className="w-32 h-5 rounded-md" />
        <div className="flex items-center gap-4">
          <Skeleton className="w-16 h-7 rounded-md" />
          <Skeleton className="w-24 h-7 rounded-md" />
          <Skeleton className="w-16 h-7 rounded-md" />
        </div>
      </div>

      <div className="space-y-4">
        {/* card */}
        <div className="glass-card p-4 hover:border-(--chart-2)/40 transition-colors group">
          <div className="flex items-center justify-between gap-4 mb-3 mt-1">
            <div className="flex gap-3">
              <Skeleton className="w-6 h-6 rounded-md" />
              <Skeleton className="w-32 h-6 rounded-md" />
            </div>

            <div className="flex items-center gap-2 font-mono text-sm  transition-colors px-2 py-1 rounded truncate max-w-50 sm:max-w-xs shrink-0">
              <GithubLogoIcon
                size={14}
                weight="fill"
                className="animate-pulse"
              />
              <Skeleton className="w-20 h-4 rounded-md" />
            </div>
          </div>
          <div className="pl-9">
            <Skeleton className="w-full h-24 rounded-md mb-3" />
            <Skeleton className="w-8 h-2.5 rounded-md" />
          </div>
        </div>
        {/* card */}
        <div className="glass-card p-4 hover:border-(--chart-2)/40 transition-colors group">
          <div className="flex items-center justify-between gap-4 mb-3 mt-1">
            <div className="flex gap-3">
              <Skeleton className="w-6 h-6 rounded-md" />
              <Skeleton className="w-32 h-6 rounded-md" />
            </div>

            <div className="flex items-center gap-2 font-mono text-sm  transition-colors px-2 py-1 rounded truncate max-w-50 sm:max-w-xs shrink-0">
              <GithubLogoIcon
                size={14}
                weight="fill"
                className="animate-pulse"
              />
              <Skeleton className="w-20 h-4 rounded-md" />
            </div>
          </div>
          <div className="pl-9">
            <Skeleton className="w-full h-24 rounded-md mb-3" />
            <Skeleton className="w-8 h-2.5 rounded-md" />
          </div>
        </div>
        {/* card */}
        <div className="glass-card p-4 hover:border-(--chart-2)/40 transition-colors group">
          <div className="flex items-center justify-between gap-4 mb-3 mt-1">
            <div className="flex gap-3">
              <Skeleton className="w-6 h-6 rounded-md" />
              <Skeleton className="w-32 h-6 rounded-md" />
            </div>

            <div className="flex items-center gap-2 font-mono text-sm  transition-colors px-2 py-1 rounded truncate max-w-50 sm:max-w-xs shrink-0">
              <GithubLogoIcon
                size={14}
                weight="fill"
                className="animate-pulse"
              />
              <Skeleton className="w-20 h-4 rounded-md" />
            </div>
          </div>
          <div className="pl-9">
            <Skeleton className="w-full h-24 rounded-md mb-3" />
            <Skeleton className="w-8 h-2.5 rounded-md" />
          </div>
        </div>
        {/* card */}
        <div className="glass-card p-4 hover:border-(--chart-2)/40 transition-colors group">
          <div className="flex items-center justify-between gap-4 mb-3 mt-1">
            <div className="flex gap-3">
              <Skeleton className="w-6 h-6 rounded-md" />
              <Skeleton className="w-32 h-6 rounded-md" />
            </div>

            <div className="flex items-center gap-2 font-mono text-sm  transition-colors px-2 py-1 rounded truncate max-w-50 sm:max-w-xs shrink-0">
              <GithubLogoIcon
                size={14}
                weight="fill"
                className="animate-pulse"
              />
              <Skeleton className="w-20 h-4 rounded-md" />
            </div>
          </div>
          <div className="pl-9">
            <Skeleton className="w-full h-24 rounded-md mb-3" />
            <Skeleton className="w-8 h-2.5 rounded-md" />
          </div>
        </div>
        {/* card */}
        <div className="glass-card p-4 hover:border-(--chart-2)/40 transition-colors group">
          <div className="flex items-center justify-between gap-4 mb-3 mt-1">
            <div className="flex gap-3">
              <Skeleton className="w-6 h-6 rounded-md" />
              <Skeleton className="w-32 h-6 rounded-md" />
            </div>

            <div className="flex items-center gap-2 font-mono text-sm  transition-colors px-2 py-1 rounded truncate max-w-50 sm:max-w-xs shrink-0">
              <GithubLogoIcon
                size={14}
                weight="fill"
                className="animate-pulse"
              />
              <Skeleton className="w-20 h-4 rounded-md" />
            </div>
          </div>
          <div className="pl-9">
            <Skeleton className="w-full h-24 rounded-md mb-3" />
            <Skeleton className="w-8 h-2.5 rounded-md" />
          </div>
        </div>
      </div>
    </main>
  );
}
