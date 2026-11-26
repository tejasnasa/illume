/**
 * Skeleton fallback for the repository settings route.
 * @module RepoSettingsLoading
 */
import Skeleton from "@/components/ui/Skeleton";

/**
 * Renders the settings sections as placeholders.
 *
 * @returns The skeleton.
 */
export default function RepoSettingsLoading() {
  return (
    <div
      aria-busy="true"
      className="mx-auto flex w-full max-w-260 flex-col px-4 pt-11 pb-16 sm:px-6"
    >
      <div className="flex flex-col gap-3 pb-8">
        <Skeleton className="h-3 w-32" />
        <Skeleton className="h-14 w-96 max-w-full" />
      </div>
      {[200, 320, 160, 110].map((h, i) => (
        <div
          key={i}
          className="grid grid-cols-1 gap-4 border-t border-(--border) py-8 md:grid-cols-[240px_minmax(0,1fr)] md:gap-8"
        >
          <div className="flex flex-col gap-2">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-3 w-48" />
            <Skeleton className="h-3 w-40" />
          </div>
          <Skeleton className="w-full rounded-md" style={{ height: h }} />
        </div>
      ))}
    </div>
  );
}
