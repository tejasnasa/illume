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
 * @param children - The doc page.
 * @returns The docs shell.
 */
export default function DocsLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="min-h-dvh bg-(--background) text-(--foreground)">
      <SiteNavbar />
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 pt-22 pb-6 sm:px-6 lg:flex-row lg:gap-10 lg:pt-26 lg:pb-10">
        <aside className="lg:sticky lg:top-24 lg:h-fit lg:w-56 lg:shrink-0">
          <DocsNav sections={listDocSections()} />
        </aside>
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </div>
  );
}
