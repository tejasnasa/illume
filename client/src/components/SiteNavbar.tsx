/**
 * The public site's top bar, shared by the landing page, the docs and the
 * signed-out contact page: wordmark, centred section links, the GitHub star
 * button and Login.
 *
 * Fixed and 4rem tall: every page that renders it pads its content down by at least
 * that much. The section links are `/#…` rather than `#…`, and go through
 * `next/link`, so from the docs they land on the landing page's section; on the
 * landing page itself they only scroll.
 * @module SiteNavbar
 */
import { GithubLogoIcon } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";
import GitHubStars from "./GitHubStars";
import { Wordmark } from "./ui/Logo";

const LINKS = [
  { href: "/#features", label: "Features" },
  { href: "/#how-it-works", label: "How it works" },
  { href: "/docs", label: "Docs" },
  { href: "/contact", label: "Contact" },
] as const;

const REPO = "tejasnasa/illume";

/**
 * Renders the public top bar.
 *
 * @returns The fixed navigation bar.
 */
export default function SiteNavbar() {
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 top-0 z-50 border-b border-(--border) bg-(--background)/85 backdrop-blur-md"
    >
      <div className="mx-auto grid h-16 max-w-7xl grid-cols-[1fr_auto_1fr] items-center gap-4 px-4 sm:px-6">
        <Link href="/" aria-label="Illume home" className="justify-self-start">
          <Wordmark />
        </Link>

        <div className="hidden items-center gap-1 font-pixel text-sm tracking-[0.06em] uppercase md:flex">
          {LINKS.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className="px-3.5 py-2.5 text-(--muted-foreground) transition-colors duration-200 hover:text-(--foreground)"
            >
              {label}
            </Link>
          ))}
        </div>

        <div className="col-start-3 flex items-center gap-2.5 justify-self-end">
          <a
            href={`https://github.com/${REPO}`}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Star Illume on GitHub"
            className="ghost hidden h-10 items-stretch overflow-hidden rounded-sm border border-(--border-strong) font-pixel text-sm text-zinc-300 sm:flex"
          >
            <span className="flex items-center px-3">
              <GithubLogoIcon size={16} weight="fill" />
            </span>
            <GitHubStars repo={REPO} />
          </a>
          <Link
            href="/login"
            className="cta flex h-10 items-center rounded-sm bg-(--primary) px-4.5 font-pixel text-sm tracking-[0.06em] text-(--primary-foreground) uppercase"
          >
            Login
          </Link>
        </div>
      </div>
    </nav>
  );
}
