/**
 * Split-screen login route: the GitHub sign-in on the left, a live graph on
 * the right.
 * @module LoginPage
 */
import PixelGraph from "@/components/PixelGraph";
import LoginForm from "@/components/LoginForm";
import { Wordmark } from "@/components/ui/Logo";
import sample from "@/data/data1.json";
import Graph from "@/types/graph";
import Link from "next/link";

const SAMPLE = sample as Graph;

/**
 * Renders the sign-in panel beside an ambient sample graph.
 *
 * The graph half is decorative and hidden below the large breakpoint, where
 * the sign-in panel takes the full width; phone visitors also get a pointer to
 * the Android app.
 *
 * @returns Login page layout.
 */
export default function Login() {
  return (
    <div className="grid min-h-dvh lg:grid-cols-2">
      <main className="relative flex min-h-dvh min-w-0 flex-col border-(--border) px-[clamp(24px,5vw,72px)] py-7 lg:border-r">
        <header className="flex items-center justify-between gap-4">
          <Link href="/" aria-label="Illume home">
            <Wordmark />
          </Link>
          <Link
            href="/mobile"
            className="font-pixel text-xs tracking-[0.08em] text-(--muted-foreground) uppercase hover:text-(--foreground) lg:hidden"
          >
            Android app ↓
          </Link>
        </header>

        <div className="flex grow items-center justify-center py-12">
          <LoginForm />
        </div>

        <footer className="flex flex-wrap justify-between gap-3 font-pixel text-[11px] tracking-[0.08em] text-(--faint-foreground) uppercase">
          <span>© {new Date().getFullYear()} Illume</span>
          <span>Built by Tejas Nasa</span>
        </footer>
      </main>

      <aside
        aria-hidden="true"
        className="sticky top-0 hidden h-dvh min-w-0 overflow-hidden bg-[radial-gradient(ellipse_at_60%_40%,#0092b81f,transparent_60%),#060608] lg:block"
      >
        <PixelGraph source={SAMPLE} />
        <span className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_55%,#060608_100%)]" />
        <div className="absolute inset-x-8 top-7 flex justify-between font-pixel text-xs tracking-[0.12em] text-(--subtle-foreground) uppercase">
          <span>A sample map</span>
          <span className="flex items-center gap-2 text-(--chart-1)">
            <span className="blink h-1.75 w-1.75 bg-(--chart-1)" />
            Live layout
          </span>
        </div>
        <div className="absolute right-8 bottom-8 text-right font-pixel text-xs leading-[1.8] tracking-[0.1em] text-(--faint-foreground) uppercase">
          {SAMPLE.nodes.length.toLocaleString("en-US")} files
          <br />
          {SAMPLE.links.length.toLocaleString("en-US")} edges
        </div>
      </aside>
    </div>
  );
}
