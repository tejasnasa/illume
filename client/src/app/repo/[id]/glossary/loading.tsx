/**
 * Skeleton fallback for the glossary route.
 * @module GlossaryLoading
 */
import Skeleton from "@/components/ui/Skeleton";

/**
 * Renders the glossary header and entry grid as placeholders.
 *
 * @returns The skeleton.
 */
export default function GlossaryLoading() {
  return (
    <div
      aria-busy="true"
      className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 pt-11 pb-16 sm:px-6"
    >
      <div className="flex flex-wrap items-end justify-between gap-5">
        <div className="flex flex-col gap-3">
          <Skeleton className="h-3 w-32" />
          <Skeleton className="h-16 w-96 max-w-full" />
          <Skeleton className="h-4 w-72 max-w-full" />
        </div>
        <Skeleton className="h-11 w-full sm:w-95" />
      </div>
      <div className="flex justify-between">
        <Skeleton className="h-3 w-40" />
        <Skeleton className="h-8 w-56" />
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="panel flex flex-col gap-3 p-5.5">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-5/6" />
            <Skeleton className="h-3 w-2/3" />
            <div className="mt-2 flex justify-between border-t border-white/8 pt-2.5">
              <Skeleton className="h-3 w-40" />
              <Skeleton className="h-3 w-24" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
