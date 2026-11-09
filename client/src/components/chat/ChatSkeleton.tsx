/**
 * Placeholders for the empty chat: greeting, composer and starter questions,
 * sized like the real pieces so nothing moves when they arrive.
 * @module ChatSkeleton
 */
import Skeleton from "@/components/ui/Skeleton";

/** Stands in for the icon and question above the composer. */
export function GreetingSkeleton() {
  return (
    <div className="mb-2 flex flex-col items-center" aria-hidden="true">
      <Skeleton className="mb-3 h-5.5 w-5.5 rounded-full" />
      <div className="flex h-8 items-center">
        <Skeleton className="h-6 w-80 max-w-[80vw]" />
      </div>
    </div>
  );
}

/** Stands in for the composer card, at its one-line height. */
export function ComposerSkeleton() {
  return (
    <div
      className="w-full rounded-2xl border border-(--border) bg-(--card)/60 p-2 backdrop-blur-xl"
      aria-hidden="true"
    >
      <div className="flex h-9 items-center px-3">
        <Skeleton className="h-3 w-40" />
      </div>
      <div className="flex items-center justify-between px-1 pt-1">
        <Skeleton className="h-8 w-24 rounded-full" />
        <Skeleton className="h-8 w-8 rounded-full" />
      </div>
    </div>
  );
}

/** Stands in for the three starter questions. */
export function SuggestionsSkeleton() {
  return (
    <div className="grid gap-2 sm:grid-cols-3" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-14 w-full rounded-xl" />
      ))}
    </div>
  );
}
