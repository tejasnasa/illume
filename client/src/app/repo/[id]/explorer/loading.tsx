/**
 * Skeleton fallback for the explorer route.
 * @module ExplorerLoading
 */
import Skeleton from "@/components/ui/Skeleton";

/** Indents of the placeholder tree rows, in 14px steps. */
const ROWS = [0, 1, 1, 2, 2, 2, 1, 0, 1, 1, 2, 0, 1, 1];

/**
 * Renders the reading-order bar, tree and detail section as placeholders.
 *
 * @returns The skeleton.
 */
export default function ExplorerLoading() {
  return (
    <div
      aria-busy="true"
      className="mx-auto flex w-full max-w-7xl flex-col gap-5 px-4 pt-8 pb-16 sm:px-6"
    >
      <div className="panel flex items-center gap-3.5 px-3.5 py-3">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="h-7 w-9" />
        <Skeleton className="h-4 w-12" />
        <Skeleton className="h-7 w-9" />
        <Skeleton className="h-1.5 grow" />
      </div>
      <div className="grid grid-cols-1 items-start gap-5 md:grid-cols-[300px_minmax(0,1fr)]">
        <div className="panel flex flex-col gap-2.5 p-4">
          <Skeleton className="mb-1 h-3 w-16" />
          {ROWS.map((level, i) => (
            <div key={i} style={{ paddingLeft: level * 14 }}>
              <Skeleton className="h-3.5" style={{ width: `${70 - level * 12}%` }} />
            </div>
          ))}
        </div>
        <div className="flex flex-col gap-4">
          <Skeleton className="h-3.5 w-40" />
          <Skeleton className="h-12 w-72 max-w-full" />
          <div className="flex gap-1.5">
            <Skeleton className="h-6 w-18" />
            <Skeleton className="h-6 w-16" />
            <Skeleton className="h-6 w-20" />
          </div>
          <Skeleton className="h-16 w-full" />
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="panel flex flex-col gap-3 p-5">
                <Skeleton className="h-3 w-28" />
                <Skeleton className="h-3 w-4/5" />
                <Skeleton className="h-3 w-3/5" />
                <Skeleton className="h-3 w-2/3" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
