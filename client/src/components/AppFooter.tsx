/**
 * Site footer shared by the signed-in pages, the contact page and the landing page.
 * @module AppFooter
 */
import Link from "next/link";

/** Social profiles, rendered in order after the internal links. */
const SOCIALS = [
  { href: "https://github.com/tejasnasa", label: "GitHub" },
  { href: "https://www.linkedin.com/in/tejasnasa/", label: "LinkedIn" },
  { href: "https://x.com/tejasnasa/", label: "X" },
];

const linkClass =
  "text-(--faint-foreground) transition-colors hover:text-(--foreground)";

/**
 * Renders the one-line footer: credit on the left, links on the right.
 *
 * `mt-auto` is what pins it: each authenticated layout is a full-height flex column, so
 * the footer is pushed to the bottom of the viewport when the page's own content is
 * shorter than the screen -- an empty dashboard -- and sits below the content when it is
 * not. Nothing wraps `children` to achieve that, so the pin depends on the page not
 * claiming a full viewport of its own height.
 *
 * `relative z-10` keeps it above an absolutely-positioned sibling, which the layout
 * systems used elsewhere in the app rely on.
 *
 * @returns The footer element.
 */
export default function AppFooter() {
  return (
    <footer className="relative z-10 mt-auto border-t border-(--border) bg-(--background)">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-5 font-pixel text-xs tracking-[0.08em] text-(--faint-foreground) uppercase sm:px-6">
        <span>© {new Date().getFullYear()} Illume · Built by Tejas Nasa</span>
        <div className="flex flex-wrap items-center gap-5">
          <Link href="/docs" className={linkClass}>
            Docs
          </Link>
          <Link href="/contact" className={linkClass}>
            Contact
          </Link>
          {SOCIALS.map(({ href, label }) => (
            <a
              key={label}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className={linkClass}
            >
              {label}
            </a>
          ))}
        </div>
      </div>
    </footer>
  );
}
