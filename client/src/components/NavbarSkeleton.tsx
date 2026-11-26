/**
 * Placeholder for the signed-in top bar while a route streams.
 * @module NavbarSkeleton
 */
import Link from "next/link";
import { Wordmark } from "./ui/Logo";

/**
 * Header placeholder matching the real Navbar's height and layout.
 *
 * The wordmark is real (it needs no data); the account button is a flat block
 * the same size as the real one, so the bar does not shift when the page lands.
 *
 * @returns The rendered header skeleton.
 */
export default function NavbarSkeleton() {
  return (
    <nav
      aria-label="Main"
      className="sticky top-0 z-40 border-b border-(--border) bg-(--background)/85 backdrop-blur-md"
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/dashboard" aria-label="Dashboard">
          <Wordmark />
        </Link>
        <div className="h-9.5 w-40 animate-pulse rounded-sm border border-(--border) bg-(--card)" />
      </div>
    </nav>
  );
}
