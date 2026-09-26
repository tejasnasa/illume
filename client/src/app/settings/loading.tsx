/**
 * Skeleton fallback for the settings route.
 *
 * Includes a `<NavbarSkeleton />` that matches the real `<Navbar />` shape
 * exactly -- same star icon and avatar dimensions, same margins -- so the
 * loading state does not shift when the real page lands. The skeleton is
 * pure divs (no <img>, no real icons) so the strict-mode Playwright concern
 * that previously excluded a real <Navbar /> here does not apply.
 * @module SettingsLoading
 */
import NavbarSkeleton from "@/components/NavbarSkeleton";
import Skeleton from "@/components/ui/Skeleton";

/**
 * Renders placeholder settings rows while the real page resolves.
 *
 * Layout mirrors `app/settings/page.tsx`: same outer container, same heading,
 * and the same `mx-auto max-w-3xl` section that wraps the AiSettings card so
 * the skeleton does not jump when the real page lands.
 *
 * @returns Skeleton settings layout mirroring the real page structure.
 */
export default function LoadingSettings() {
  return (
    <div className="min-h-screen">
      <NavbarSkeleton />
      <main className="max-w-7xl mx-auto px-6 py-24 flex items-start flex-wrap">
        <header className="flex flex-col md:flex-row justify-between items-start md:items-end gap-6 mb-16">
          <div>
            <h1 className="text-8xl font-extrabold tracking-tight animate-pulse text-(--muted-foreground)/70">
              Settings
            </h1>
          </div>
        </header>

        <section className="space-y-6 mx-auto max-w-3xl w-full">
          <div className="rounded-sm border border-(--primary)/20 divide-y divide-(--primary)/10 p-2">
            <div className="px-5 py-3">
              <Skeleton className="h-3 w-24 rounded-full" />
            </div>

            <div className="px-5 py-4 space-y-4">
              <Skeleton className="h-3 w-full max-w-md rounded-full" />

              <div className="flex flex-col my-4 gap-1">
                <Skeleton className="h-3 w-16 rounded-full" />
                <Skeleton className="h-11 w-full rounded-sm" />
              </div>

              <div className="flex flex-col my-4 gap-1">
                <Skeleton className="h-3 w-16 rounded-full" />
                <Skeleton className="h-11 w-full rounded-sm" />
                <Skeleton className="h-3 w-3/4 rounded-full" />
              </div>

              <div className="flex flex-col my-4 gap-1">
                <Skeleton className="h-3 w-16 rounded-full" />
                <Skeleton className="h-11 w-full rounded-sm" />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                <Skeleton className="h-9 w-32 rounded-sm" />
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
