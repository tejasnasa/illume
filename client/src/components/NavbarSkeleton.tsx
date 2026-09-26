import { StarFourIcon } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

/**
 * Header placeholder matching the real Navbar's dimensions and shape.
 *
 * Renders a star-icon block on the left and an avatar circle on the right at
 * the exact heights/widths/margins the real Navbar uses, so the loading state
 * doesn't shift when the real component lands. The star and avatar are flat
 * blocks (no icons, no <img>) -- the route is unauthenticated at the loading
 * boundary and the real Navbar is server-rendered, so reproducing either
 * here would either duplicate state or trigger a `next/image` call that
 * can't run in this environment.
 *
 * @returns The rendered header skeleton.
 */
export default function NavbarSkeleton() {
  return (
    <header className="flex justify-between">
      <Link
        href={"/"}
        className="relative h-16 w-16 flex items-center justify-center m-2"
      >
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="h-10 w-10 rounded-full bg-(--chart-1)/30 blur-xl" />
        </div>
        <StarFourIcon
          className="relative text-(--chart-1)"
          weight="fill"
          size={24}
        />
      </Link>

      <div className="h-12 w-12 rounded-full m-6 bg-(--muted)/50 border border-(--border) animate-pulse" />
    </header>
  );
}
