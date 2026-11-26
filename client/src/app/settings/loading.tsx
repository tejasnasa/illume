/**
 * Skeleton fallback for the settings route.
 *
 * Includes a `<NavbarSkeleton />` that matches the real `<Navbar />` shape,
 * so the loading state does not shift when the real page lands. The skeleton
 * is pure divs (no <img>, no real icons) so the strict-mode Playwright
 * concern that previously excluded a real <Navbar /> here does not apply.
 * @module SettingsLoading
 */
import NavbarSkeleton from "@/components/NavbarSkeleton";
import Skeleton from "@/components/ui/Skeleton";

/** Placeholder heights of the section cards, top to bottom. */
const SECTIONS = [96, 300, 130, 170, 420];

/**
 * Renders placeholder settings sections while the real page resolves.
 *
 * Layout mirrors `app/settings/page.tsx`: the same container, the same
 * header block and the same two-column sections.
 *
 * @returns Skeleton settings layout mirroring the real page structure.
 */
export default function LoadingSettings() {
  return (
    <div>
      <NavbarSkeleton />
      <div
        aria-busy="true"
        className="mx-auto flex w-full max-w-260 flex-col px-4 pt-11 pb-16 sm:px-6"
      >
        <div className="flex flex-col gap-3 pb-8">
          <Skeleton className="h-3 w-32" />
          <Skeleton className="h-14 w-80 max-w-full" />
        </div>
        {SECTIONS.map((height, i) => (
          <div
            key={i}
            className="grid grid-cols-1 gap-4 border-t border-(--border) py-8 md:grid-cols-[240px_minmax(0,1fr)] md:gap-8"
          >
            <div className="flex flex-col gap-2">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-3 w-48" />
              <Skeleton className="h-3 w-40" />
            </div>
            <Skeleton className="w-full rounded-md" style={{ height }} />
          </div>
        ))}
      </div>
    </div>
  );
}
