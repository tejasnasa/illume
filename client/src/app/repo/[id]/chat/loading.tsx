/**
 * Skeleton fallback for the chat route.
 * @module ChatLoading
 */
import {
  ComposerSkeleton,
  ConversationSidebarSkeleton,
  GreetingSkeleton,
  SuggestionsSkeleton,
} from "@/components/chat/ChatSkeleton";

/**
 * Renders the empty chat's layout in placeholders, laid out exactly as the
 * chat page lays it out while its history loads: the conversation panel on the
 * left on wide screens, and the greeting, composer and starter questions
 * centred in the space beside it.
 *
 * @returns Conversation panel, greeting, composer and starter-question skeleton.
 */
export default function ChatLoading() {
  return (
    <div className="fixed inset-x-0 bottom-0 top-16 overflow-hidden">
      <ConversationSidebarSkeleton />
      <div className="absolute inset-y-0 right-0 left-0 md:left-64">
        <div className="absolute inset-0 flex flex-col items-center justify-center px-4 pb-4">
          <div className="flex w-full max-w-3xl flex-col gap-3">
            <GreetingSkeleton />
            <ComposerSkeleton />
            <SuggestionsSkeleton />
          </div>
        </div>
      </div>
    </div>
  );
}
