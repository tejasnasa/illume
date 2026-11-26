/**
 * Skeleton fallback for the dashboard route.
 *
 * Includes a `<NavbarSkeleton />` so the header dimensions match the real
 * page exactly -- no jump when the route resolves.
 * @module DashboardLoading
 */
import NavbarSkeleton from "@/components/NavbarSkeleton";
import Skeleton from "@/components/ui/Skeleton";

/**
 * One placeholder card, shaped like a repository card.
 *
 * @returns The card skeleton.
 */
function CardSkeleton() {
  return (
    <div className="panel flex flex-col overflow-hidden">
      <div className="h-32 animate-pulse border-b border-white/8 bg-[#060608]" />
      <div className="flex flex-col gap-3 p-4.5">
        <Skeleton className="h-5 w-40 rounded-sm" />
        <Skeleton className="h-3 w-28 rounded-sm" />
        <Skeleton className="h-3 w-full rounded-sm" />
        <Skeleton className="h-3 w-4/5 rounded-sm" />
        <div className="mt-2 flex gap-1.5">
          <Skeleton className="h-6 w-16 rounded-[3px]" />
          <Skeleton className="h-6 w-14 rounded-[3px]" />
        </div>
        <div className="flex justify-between border-t border-white/8 pt-3">
          <Skeleton className="h-3 w-24 rounded-sm" />
          <Skeleton className="h-3 w-12 rounded-sm" />
        </div>
      </div>
    </div>
  );
}

/**
 * Renders placeholder repo cards while dashboard data loads.
 *
 * @returns Skeleton dashboard layout mirroring the real page structure.
 */
export default function LoadingDashboard() {
  return (
    <div className="flex min-h-dvh flex-col">
      <NavbarSkeleton />
      <main
        aria-busy="true"
        className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-4 pt-14 pb-24 sm:px-6"
      >
        <header className="flex flex-wrap items-end justify-between gap-6">
          <div className="flex flex-col gap-3">
            <p
              aria-hidden="true"
              className="m-0 font-pixel text-[13px] tracking-[0.08em] text-(--subtle-foreground)"
            >
              <span className="text-(--accent)">&gt;</span> illume ls
              <span className="caret">_</span>
            </p>
            <h1 className="m-0 text-4xl font-medium tracking-tight sm:text-5xl">
              Your <span className="font-pixel text-(--accent)">repositories</span>
            </h1>
            <Skeleton className="h-3 w-32 rounded-sm" />
          </div>
          <Skeleton className="h-11 w-44 rounded-sm" />
        </header>

        <div className="flex flex-wrap gap-3">
          <Skeleton className="h-10 w-72 rounded-sm" />
          <Skeleton className="h-10 w-64 rounded-sm" />
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      </main>
    </div>
  );
}
