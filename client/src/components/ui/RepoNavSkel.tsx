/**
 * Loading placeholder for the repository navigation header.
 * @module RepoNavSkel
 */
import Logo from "./Logo";
import PixelGear from "./PixelGear";
import Skeleton from "./Skeleton";

const LABELS = ["Overview", "Chat", "Graph", "Explorer", "Glossary"];

/**
 * Renders a header the same height and layout as the real repository bar.
 * @returns The rendered skeleton header element.
 */
export default function RepoNavSkel() {
  return (
    <nav
      aria-label="Repository"
      className="sticky top-0 z-40 border-b border-(--border) bg-(--background)/85 backdrop-blur-md print:hidden"
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
        <div className="flex items-center gap-3.5">
          <Logo />
          <span aria-hidden="true" className="text-zinc-700">
            /
          </span>
          <Skeleton className="h-4 w-40" />
        </div>
        <div className="flex items-center gap-3.5">
          <div className="hidden items-center font-pixel text-[13px] tracking-[0.06em] text-(--faint-foreground) uppercase md:flex">
            {LABELS.map((label) => (
              <span key={label} className="px-3">
                {label}
              </span>
            ))}
          </div>
          <span className="flex rounded-sm border border-(--border) p-2 text-(--faint-foreground)">
            <PixelGear />
          </span>
        </div>
      </div>
    </nav>
  );
}
