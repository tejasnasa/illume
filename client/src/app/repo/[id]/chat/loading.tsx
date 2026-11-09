/**
 * Skeleton fallback for the chat route.
 * @module ChatLoading
 */
import {
  ComposerSkeleton,
  GreetingSkeleton,
  SuggestionsSkeleton,
} from "@/components/chat/ChatSkeleton";

/**
 * Renders the empty chat's layout in placeholders, laid out exactly as the
 * chat page lays it out while its history loads.
 *
 * @returns Centred greeting, composer and starter-question skeleton.
 */
export default function ChatLoading() {
  return (
    <div className="fixed inset-x-0 bottom-0 top-16 overflow-hidden">
      <div className="absolute inset-0 flex flex-col items-center justify-center px-4 pb-4">
        <div className="flex w-full max-w-3xl flex-col gap-3">
          <GreetingSkeleton />
          <ComposerSkeleton />
          <SuggestionsSkeleton />
        </div>
      </div>
    </div>
  );
}
