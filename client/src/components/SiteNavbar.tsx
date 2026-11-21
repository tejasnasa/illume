/**
 * The public site's top bar, shared by the landing page and the docs: logo, section
 * links, Docs, Contact and the Login button.
 *
 * Fixed and 4rem tall: every page that renders it pads its content down by at least
 * that much. The section links are `/#…` rather than `#…`, and go through
 * `next/link`, so from the docs they land on the landing page's section; on the
 * landing page itself they only scroll.
 * @module SiteNavbar
 */
import { StarFourIcon } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

const LINKS = [
  { href: "/#features", label: "Features" },
  { href: "/#how-it-works", label: "How It Works" },
  { href: "/docs", label: "Docs" },
  { href: "/contact", label: "Contact" },
] as const;

/**
 * Renders the public top bar.
 *
 * @returns The fixed navigation bar.
 */
export default function SiteNavbar() {
  return (
    <nav className="fixed top-0 inset-x-0 z-50 backdrop-blur-xl border-b border-(--border)">
      <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
        <Link
          href={"/"}
          className="relative h-12 flex items-center justify-center m-2 gap-2"
        >
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="h-10 w-40 rounded-full bg-(--chart-1)/30 blur-xl" />
          </div>
          <StarFourIcon
            className="relative text-(--chart-1)"
            weight="fill"
            size={24}
          />
          <span className="text-xl font-semibold">Illume</span>
        </Link>

        <div className="flex items-center gap-1">
          {LINKS.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className="hidden sm:block px-4 py-2 text-sm text-(--muted-foreground) hover:text-(--foreground) rounded-lg hover:bg-(--secondary) transition-all duration-200"
            >
              {label}
            </Link>
          ))}
          <Link
            href="/login"
            className="ml-2 flex items-center gap-2 px-4 py-2 text-sm rounded-full border bg-(--primary) border-(--border)  hover:border-white transition-all duration-200"
          >
            <span className="sm:inline">Login</span>
          </Link>
        </div>
      </div>
    </nav>
  );
}
