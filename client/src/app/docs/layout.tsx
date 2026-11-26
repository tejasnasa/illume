/**
 * Shell for every `/docs` page: the same navbar as the landing page, the grouped
 * sidebar (a dropdown on phones), and the content column. Public: the auth proxy
 * neither guards `/docs` nor redirects a signed-in visitor away from it.
 * @module DocsLayout
 */
import SiteNavbar from "@/components/SiteNavbar";
import { DocsNav } from "@/components/docs/DocsNav";
import { listDocSections } from "@/lib/docs";
import "./docs.css";

/**
 * Wraps docs pages with the site navbar and the docs sidebar.
 *
 * From `lg` up the sidebar is pinned below the navbar at full viewport height
 * and scrolls on its own, so a long doc never drags the navigation away.
 *
 * @param children - The doc page.
 * @returns The docs shell.
 */
export default function DocsLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="min-h-dvh text-(--foreground)">
      <SiteNavbar />
      <div className="mx-auto grid w-full max-w-340 grid-cols-1 items-start px-4 pt-16 sm:px-6 lg:grid-cols-[240px_minmax(0,1fr)] lg:gap-12">
        <aside className="border-b border-white/10 py-6 lg:sticky lg:top-16 lg:h-[calc(100dvh-4rem)] lg:overflow-y-auto lg:overscroll-contain lg:border-r lg:border-b-0 lg:py-8 lg:pr-5 custom-scrollbar">
          <DocsNav sections={listDocSections()} />
        </aside>
        <div className="min-w-0">{children}</div>
      </div>
    </div>
  );
}
