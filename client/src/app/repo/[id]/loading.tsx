/**
 * Skeleton fallback for the repository overview route.
 * @module RepoLoading
 */
import Skeleton from "@/components/ui/Skeleton";
import {
  AtomIcon,
  BookOpenIcon,
  ChartBarIcon,
  GithubLogoIcon,
  LinkIcon,
  ClockCounterClockwiseIcon,
  TreeStructureIcon,
} from "@phosphor-icons/react/dist/ssr";

function CardTitle({
  icon: Icon,
  title,
}: {
  icon: React.ElementType;
  title: string;
}) {
  return (
    <h2 className="mb-4 flex shrink-0 items-center gap-2 text-lg font-bold text-(--foreground)">
      <Icon size={20} className="text-(--primary)" />
      {title}
    </h2>
  );
}

/**
 * Renders placeholder overview panels in the same layout as the loaded page,
 * so nothing shifts when the content arrives.
 *
 * @returns Skeleton repository overview layout.
 */
export default function LoadingDashboard() {
  return (
    <main className="p-4 flex flex-col gap-4 max-w-7xl mx-auto lg:h-[calc(100vh-64px)] lg:flex-row">
      <section className="w-full flex flex-col gap-4 lg:h-full lg:w-1/2">
        <div className="grid grid-cols-1 gap-4 shrink-0 sm:grid-cols-2 sm:h-30">
          <div className="relative glass-card rounded-sm overflow-hidden">
            <div className="absolute top-4 right-4 text-(--muted-foreground)">
              <LinkIcon size={20} />
            </div>
            <div className="p-4 flex flex-col justify-between h-full gap-4">
              <span className="text-xs font-semibold uppercase tracking-wider text-(--muted-foreground)">
                Repository
              </span>
              <div className="flex items-center gap-3">
                <GithubLogoIcon
                  size={28}
                  weight="fill"
                  className="text-(--muted-foreground) shrink-0"
                />
                <Skeleton className="h-6 w-40" />
              </div>
            </div>
          </div>

          <div className="glass-card rounded-sm p-4 flex flex-col justify-between gap-4">
            <span className="text-xs font-semibold uppercase tracking-wider text-(--muted-foreground)">
              Processing Status
            </span>
            <div className="flex items-end justify-between">
              <Skeleton className="h-6 w-24" />
              <div className="flex flex-col items-end gap-1.5">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-3 w-20" />
              </div>
            </div>
          </div>
        </div>

        <div className="glass-card rounded-sm p-4 flex-1 min-h-80 flex flex-col lg:min-h-0">
          <CardTitle icon={TreeStructureIcon} title="AI Architecture Overview" />
          <div className="space-y-3 flex-1">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-11/12" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        </div>

        <div className="glass-card rounded-sm p-4 shrink-0 flex flex-col">
          <CardTitle icon={AtomIcon} title="Tech Stack Detected" />
          <div className="grid grid-cols-2 gap-x-6 gap-y-3">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i}>
                <Skeleton className="w-20 h-3 mb-2" />
                <div className="flex gap-1.5">
                  <Skeleton className="w-12 h-4" />
                  <Skeleton className="w-16 h-4" />
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="w-full flex flex-col gap-4 lg:h-full lg:w-1/2">
        <div className="glass-card rounded-sm p-4 shrink-0 flex flex-col">
          <CardTitle icon={ChartBarIcon} title="At a Glance" />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex flex-col gap-1.5">
                <Skeleton className="h-6 w-12" />
                <Skeleton className="h-2.5 w-16" />
              </div>
            ))}
          </div>
          <Skeleton className="mt-4 h-2.5 w-full rounded-full" />
          <div className="mt-2 flex gap-4">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-3 w-14" />
          </div>
        </div>

        <div className="glass-card rounded-sm p-4 flex-[9] min-h-0 flex flex-col overflow-hidden">
          <CardTitle icon={BookOpenIcon} title="Start Here" />
          <div className="space-y-3">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="flex gap-3">
                <Skeleton className="h-5 w-5 shrink-0 rounded-full" />
                <div className="flex-1 space-y-1.5">
                  <Skeleton className="h-3 w-1/2" />
                  <Skeleton className="h-3 w-11/12" />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="glass-card rounded-sm p-4 flex-[5] min-h-0 flex flex-col overflow-hidden">
          <CardTitle icon={ClockCounterClockwiseIcon} title="Recent Activity" />
          <div className="space-y-2.5">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="flex items-start gap-2.5">
                <Skeleton className="mt-0.5 h-3.5 w-3.5 shrink-0 rounded-full" />
                <div className="flex-1 space-y-1">
                  <Skeleton className="h-3 w-3/4" />
                  <Skeleton className="h-2.5 w-1/3" />
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
