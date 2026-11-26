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
      <Skeleton className="mb-3 h-3 w-40" />
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
      className="w-full rounded-md border border-(--input) bg-(--card) p-3"
      aria-hidden="true"
    >
      <div className="flex h-9 items-center px-3">
        <Skeleton className="h-3 w-40" />
      </div>
      <div className="flex items-center justify-between px-1 pt-1">
        <Skeleton className="h-8 w-28 rounded-sm" />
        <Skeleton className="h-8 w-20 rounded-sm" />
      </div>
    </div>
  );
}

/** Stands in for the three starter questions. */
export function SuggestionsSkeleton() {
  return (
    <div className="grid gap-2 sm:grid-cols-3" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-14 w-full rounded-sm" />
      ))}
    </div>
  );
}

/** Stands in for the conversation list's rows while it loads. */
export function ConversationRowsSkeleton() {
  return (
    <li
      className="space-y-1 px-2"
      aria-hidden="true"
      data-testid="conversation-rows-skeleton"
    >
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="space-y-1.5 px-3 py-2">
          <Skeleton className="h-3.5 w-4/5" />
          <Skeleton className="h-2.5 w-1/3" />
        </div>
      ))}
    </li>
  );
}

/**
 * Stands in for the conversation panel on wide screens, and for the button
 * that opens it on narrow ones, in the places the chat page puts them.
 */
export function ConversationSidebarSkeleton() {
  return (
    <>
      <div
        className="absolute inset-y-0 left-0 z-30 hidden w-65 md:block"
        aria-hidden="true"
      >
        <div className="flex h-full w-full flex-col border-r border-(--border) bg-(--background)">
          <div className="p-4">
            <Skeleton className="h-10 w-full rounded-sm" />
          </div>
          <ul className="flex-1 overflow-hidden pb-3">
            <ConversationRowsSkeleton />
          </ul>
        </div>
      </div>
      <div className="absolute left-3 top-3 z-20 md:hidden" aria-hidden="true">
        <Skeleton className="h-7.5 w-20 rounded-sm" />
      </div>
    </>
  );
}
