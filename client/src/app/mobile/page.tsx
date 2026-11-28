/**
 * Download page for the Android app.
 * @module MobilePage
 */
import PixelGraph from "@/components/PixelGraph";
import { Wordmark } from "@/components/ui/Logo";
import sample from "@/data/data3.json";
import Graph from "@/types/graph";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Illume for Android",
  description:
    "Your repositories, the 3D dependency graph and the codebase chat, built for touch.",
};

/** The published app version, shown on the download button. */
const APK_VERSION = "v0.1.0";

/**
 * Where the APK is published. Every app release attaches the build as
 * `illume.apk`, and GitHub serves the latest release's asset at this fixed
 * path, so the button downloads the current build without per-version edits.
 */
const APK_URL =
  "https://github.com/tejasnasa/illume/releases/latest/download/illume.apk";

const INSTALL_STEPS: [string, string][] = [
  ["Download the APK", "Tap the button above. It saves to your Downloads."],
  [
    "Allow the install",
    "Android asks once to let your browser install apps. Say yes.",
  ],
  [
    "Log in with GitHub",
    "Open Illume and continue with GitHub. Your repositories are waiting.",
  ],
];

/**
 * Renders the phone-first download page: a small live graph, the Android
 * download, the (unavailable) iPhone slot and the install steps. On a phone
 * they stack in one column; from tablet width up the graph and the copy sit
 * side by side, centred in the screen.
 *
 * @returns The mobile download page.
 */
export default function MobilePage() {
  return (
    <div className="flex min-h-dvh justify-center">
      <main className="flex w-full max-w-120 flex-col gap-7 px-[clamp(24px,5vw,72px)] pt-5 pb-8 md:max-w-none md:gap-10 md:py-7">
        <header className="flex items-center justify-between">
          <Link href="/" aria-label="Illume home">
            <Wordmark />
          </Link>
        </header>

        <div className="flex flex-col gap-7 md:my-auto md:grid md:grid-cols-2 md:items-center md:gap-12 lg:gap-20">
          <div
            aria-hidden="true"
            className="relative aspect-square overflow-hidden rounded-md border border-(--border) bg-[radial-gradient(ellipse_at_50%_45%,#0092b826,transparent_65%),#060608]"
          >
            <PixelGraph
              source={sample as Graph}
              spin
              draggable
              cell={3}
              focusLabel={false}
              spreadY={0.42}
              lightRadius={0.34}
            />
            <span className="pointer-events-none absolute bottom-3 left-3.5 font-pixel text-[11px] tracking-[0.12em] text-(--faint-foreground) uppercase">
              Drag to spin
            </span>
            <span className="pointer-events-none absolute top-3 right-3.5 flex items-center gap-1.5 font-pixel text-[11px] tracking-[0.12em] text-(--chart-1) uppercase">
              <span className="blink h-1.5 w-1.5 bg-(--chart-1)" />
              3D, on your phone
            </span>
          </div>

          <div className="flex flex-col gap-7">
            <div className="flex flex-col gap-3">
              <h1 className="m-0 font-pixel text-[2.6rem] leading-[1.02] tracking-[-0.02em] md:text-[3.4rem] lg:text-[4.2rem]">
                Illume,
                <br />
                <span className="gradient-text">in your pocket</span>
              </h1>
              <p className="m-0 text-base leading-relaxed text-zinc-400 md:text-lg">
                Your repositories, the 3D graph and the codebase chat, built for
                touch.
              </p>
            </div>

            <div className="flex flex-col gap-2.5">
              <a
                href={APK_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="cta flex items-center gap-3.5 rounded-sm bg-(--primary) px-4.5 py-4 text-(--primary-foreground)"
              >
                <svg
                  width="26"
                  height="26"
                  viewBox="0 0 12 12"
                  shapeRendering="crispEdges"
                  fill="currentColor"
                  aria-hidden="true"
                >
                  <path d="M5 1h2v4h2v1H8v1H7v1H5V7H4V6H3V5h2zM1 9h10v2H1z" />
                </svg>
                <span className="flex grow flex-col gap-0.5">
                  <span className="font-pixel text-[17px] tracking-[0.02em]">
                    Download for Android
                  </span>
                  <span className="font-pixel text-[11px] tracking-[0.08em] text-(--primary-foreground)/70 uppercase">
                    APK · {APK_VERSION}
                  </span>
                </span>
                <span aria-hidden="true" className="font-pixel text-lg">
                  ↓
                </span>
              </a>
              <div
                aria-disabled="true"
                className="flex items-center gap-3.5 rounded-sm border border-dashed border-(--input) px-4.5 py-4 text-(--subtle-foreground)"
              >
                <svg
                  width="26"
                  height="26"
                  viewBox="0 0 12 12"
                  shapeRendering="crispEdges"
                  fill="currentColor"
                  aria-hidden="true"
                >
                  <path
                    fillRule="evenodd"
                    d="M2 1h8v10H2zM3 2v7h6V2zM5 9.5v1h2v-1z"
                  />
                </svg>
                <span className="flex grow flex-col gap-0.5">
                  <span className="font-pixel text-[17px]">iPhone</span>
                  <span className="font-pixel text-[11px] tracking-[0.08em] uppercase">
                    Not available yet
                  </span>
                </span>
              </div>
            </div>

            <section
              aria-labelledby="install-h"
              className="panel flex flex-col gap-3.5 p-4.5"
            >
              <h2 id="install-h" className="eyebrow m-0">
                Installing the APK
              </h2>
              <ol className="m-0 flex list-none flex-col gap-3.5 p-0">
                {INSTALL_STEPS.map(([title, desc], i) => (
                  <li key={title} className="flex items-start gap-3.5">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center border border-(--input) font-pixel text-[13px] text-(--muted-foreground)">
                      0{i + 1}
                    </span>
                    <span className="flex flex-col gap-0.5 pt-0.75">
                      <span className="text-[15px]">{title}</span>
                      <span className="text-[13px] leading-normal text-(--muted-foreground)">
                        {desc}
                      </span>
                    </span>
                  </li>
                ))}
              </ol>
            </section>
          </div>
        </div>

        <footer className="mt-auto flex justify-between gap-3 font-pixel text-[11px] tracking-[0.08em] text-(--faint-foreground) uppercase">
          <span>© {new Date().getFullYear()} Illume</span>
          <span>Built by Tejas Nasa</span>
        </footer>
      </main>
    </div>
  );
}
