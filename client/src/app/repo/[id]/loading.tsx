/**
 * Skeleton fallback for the repository overview.
 * @module RepositoryLoading
 */
import Skeleton from "@/components/ui/Skeleton";

/** Placeholder bento cards: grid span and body height. */
const CARDS: { span: string; height: number }[] = [
  { span: "lg:col-span-8 lg:row-span-2", height: 420 },
  { span: "lg:col-span-4", height: 200 },
  { span: "lg:col-span-4", height: 180 },
  { span: "lg:col-span-4", height: 240 },
  { span: "lg:col-span-4", height: 240 },
  { span: "lg:col-span-4", height: 240 },
];

/**
 * Renders the overview header and bento grid as placeholders.
 *
 * @returns The skeleton.
 */
export default function RepositoryLoading() {
  return (
    <div
      aria-busy="true"
      className="mx-auto flex w-full max-w-7xl flex-col gap-7 px-4 pt-11 pb-16 sm:px-6"
    >
      <div className="flex flex-wrap items-end justify-between gap-6">
        <div className="flex flex-col gap-3.5">
          <div className="flex gap-2.5">
            <Skeleton className="h-6.5 w-18" />
            <Skeleton className="h-6.5 w-36" />
            <Skeleton className="h-6.5 w-32" />
          </div>
          <Skeleton className="h-16 w-80 max-w-full" />
          <Skeleton className="h-3.5 w-56" />
        </div>
        <Skeleton className="h-21 w-full rounded-sm sm:w-115" />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        {CARDS.map((card, i) => (
          <div key={i} className={`panel flex flex-col gap-4 p-5.5 ${card.span}`}>
            <Skeleton className="h-3 w-32" />
            <Skeleton className="w-full" style={{ height: card.height }} />
          </div>
        ))}
      </div>
    </div>
  );
}
