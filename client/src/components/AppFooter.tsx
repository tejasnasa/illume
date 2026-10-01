/**
 * Site footer for the signed-in application shell.
 * @module AppFooter
 */
import {
  GithubLogoIcon,
  LinkedinLogoIcon,
  StarFourIcon,
  XLogoIcon,
} from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

/** Social profiles, rendered in order. */
const SOCIALS = [
  { href: "https://github.com/tejasnasa", label: "GitHub", Icon: GithubLogoIcon },
  {
    href: "https://www.linkedin.com/in/tejasnasa/",
    label: "LinkedIn",
    Icon: LinkedinLogoIcon,
  },
  { href: "https://x.com/tejasnasa/", label: "X", Icon: XLogoIcon },
];

/**
 * Renders the footer shown beneath the signed-in pages.
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
    <footer className="relative z-10 mt-auto border-t border-(--border) pt-3 pb-6 px-6">
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <div className="relative h-10 w-10 flex items-center justify-center">
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="h-8 w-8 rounded-full bg-(--chart-1)/30 blur-xl" />
            </div>
            <StarFourIcon
              className="relative text-(--chart-1)"
              weight="fill"
              size={20}
            />
          </div>
          <span className="text-sm text-(--muted-foreground)">
            Illume &middot; Built by Tejas Nasa
          </span>
        </div>

        <div className="flex items-center gap-5">
          <Link
            href="/contact"
            className="text-sm text-(--muted-foreground) hover:text-(--foreground) transition-colors"
          >
            Contact
          </Link>

          <div className="flex items-center gap-4 text-2xl text-(--muted-foreground)">
            {SOCIALS.map(({ href, label, Icon }) => (
              <a
                key={label}
                href={href}
                target="_blank"
                rel="noreferrer"
                aria-label={label}
                className="hover:text-(--foreground) transition-colors"
              >
                <Icon />
              </a>
            ))}
          </div>
        </div>
      </div>
    </footer>
  );
}
