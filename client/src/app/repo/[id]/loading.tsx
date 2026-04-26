import Skeleton from "@/components/ui/Skeleton";
import { GithubLogoIcon, LinkIcon } from "@phosphor-icons/react/dist/ssr";

export default function LoadingDashboard() {
  return (
    <main className="p-4 h-[calc(100vh-64px)] flex gap-4 max-w-7xl mx-auto">
      <section className="w-1/2 flex flex-col gap-4 h-full">
        <div className="grid grid-cols-2 gap-4 h-30 shrink-0">
          <div className="group relative glass-card rounded-sm overflow-hidden hover:border-(--primary)/50 transition-colors">
            <div className="absolute inset-0 bg-linear-to-br from-(--primary)/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
            <div className="absolute top-4 right-4 text-(--muted-foreground) group-hover:text-(--foreground) transition-colors">
              <LinkIcon size={20} />
            </div>
            <div className="p-4 flex flex-col justify-between h-full">
              <span className="text-xs font-semibold uppercase tracking-wider text-(--muted-foreground) animate-pulse">
                Repository
              </span>
              <h2 className="text-2xl font-bold flex items-center gap-3 text-(--foreground) truncate">
                <GithubLogoIcon
                  size={28}
                  weight="fill"
                  className="text-(--muted-foreground) animate-pulse shrink-0"
                />
                <Skeleton className="h-6 w-32" />
              </h2>
            </div>
          </div>

          <div className="glass-card rounded-sm p-4 flex flex-col justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-(--muted-foreground) animate-pulse">
              Processing Status
            </span>
            <div className="flex items-end justify-between">
              <div>
                <div className="flex items-center gap-2 font-bold text-xl uppercase ">
                  <Skeleton className="h-5 w-20" />
                </div>
              </div>
              <div className="text-right text-xs text-(--muted-foreground)">
                <Skeleton className="h-3 w-16" />
              </div>
            </div>
          </div>
        </div>

        <div className="glass-card rounded-sm p-6 flex-1 min-h-0 flex flex-col border border-(--border) bg-(--secondary)/10">
          <Skeleton className="w-48 h-6 mb-6" />
          <div className="space-y-3 flex-1">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-11/12" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        </div>

        <div className="glass-card rounded-sm p-6 shrink-0 h-40 flex flex-col border border-(--border) bg-(--secondary)/10">
          <Skeleton className="w-32 h-5 mb-4" />
          <div className="grid grid-cols-2 gap-x-8 gap-y-4">
            <div>
              <Skeleton className="w-20 h-3 mb-2" />
              <div className="flex gap-2">
                <Skeleton className="w-12 h-5" />
                <Skeleton className="w-16 h-5" />
              </div>
            </div>
            <div>
              <Skeleton className="w-24 h-3 mb-2" />
              <div className="flex gap-2">
                <Skeleton className="w-14 h-5" />
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="w-1/2 h-full flex flex-col glass-card rounded-sm overflow-hidden border border-(--border)">
        <div className="w-full h-full flex flex-col">
          <div className="flex items-center justify-between p-4 shrink-0 border-b bg-(--background)/50">
            <h2 className="text-xl font-bold flex items-center gap-2 animate-pulse text-(--muted-foreground)">
              <span className="w-2.5 h-2.5 rounded-full bg-(--muted-foreground) shadow-[0_0_8px_var(--primary)] " />
              Chat with Codebase
            </h2>
          </div>

          <div className="flex-1 overflow-y-auto flex flex-col gap-4 p-2 min-h-0 custom-scrollbar justify-between">
            <div></div>
            <div className="relative">
              <Skeleton className="h-32 w-full rounded-sm" />
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
