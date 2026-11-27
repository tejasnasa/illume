/**
 * Marketing landing page: hero, stats, features, walkthrough, FAQ and footer.
 * @module HomePage
 */
import PixelGraph from "@/components/PixelGraph";
import SiteNavbar from "@/components/SiteNavbar";
import {
  AskDemo,
  BriefDemo,
  GlossaryDemo,
  McpDemo,
  ReadingOrderDemo,
} from "@/components/landing/FeatureDemos";
import HowItWorks from "@/components/landing/HowItWorks";
import { EndCta, Faq, Tour } from "@/components/landing/LandingExtras";
import Logo from "@/components/ui/Logo";
import SystemStatus from "@/components/SystemStatus";
import Link from "next/link";

const STATS: {
  n: string;
  label: [string, string];
  desc: string;
  tone?: string;
}[] = [
  {
    n: "01",
    label: ["URL to", "start"],
    desc: "Paste a GitHub link. Nothing to install or configure.",
  },
  {
    n: "13",
    label: ["Languages", "parsed"],
    desc: "Python, TypeScript, Go, Rust, Java, Kotlin and more.",
  },
  {
    n: "06",
    label: ["Guides per", "repo"],
    desc: "Graph, brief, reading order, glossary, owners and chat.",
    tone: "text-(--accent)",
  },
  {
    n: "07",
    label: ["Ways to", "search"],
    desc: "Meaning, keyword, symbol, grep, imports, co-change, history.",
  },
  {
    n: "00",
    label: ["Write access", "needed"],
    desc: "Read-only. Illume never changes your code.",
    tone: "text-(--chart-1)",
  },
];

const OWNERS: [string, number, string][] = [
  ["Aarav Kapoor", 72, "#f6339a"],
  ["Sofia Martins", 41, "#00b8db"],
  ["Jonah Reyes", 23, "#0092b8"],
  ["Priya Desai", 9, "#3f3f46"],
];

const COMMITS: [string, string][] = [
  ["a3f9c1", "fix: resolve imports with extensions"],
  ["7be210", "feat: docs navbar"],
  ["c41d0e", "refactor: split file graph"],
  ["19af77", "feat: push on sync"],
  ["e02b5c", "fix: lease expiry"],
  ["5d8e3a", "feat: MCP ask tool"],
];

const FOOTER_COLUMNS: {
  title: string;
  links: { label: string; href: string; external?: boolean }[];
}[] = [
  {
    title: "Product",
    links: [
      { label: "Features", href: "#features" },
      { label: "How it works", href: "#how-it-works" },
      { label: "The tour", href: "#tour" },
      { label: "FAQ", href: "#faq" },
    ],
  },
  {
    title: "Resources",
    links: [
      { label: "Docs", href: "/docs" },
      {
        label: "GitHub",
        href: "https://github.com/tejasnasa/illume",
        external: true,
      },
      {
        label: "YouTube",
        href: "https://www.youtube.com/watch?v=ZKjFKBAj89g",
        external: true,
      },
    ],
  },
  {
    title: "Account",
    links: [
      { label: "Get the mobile app", href: "/mobile" },
      { label: "Login", href: "/login" },
      { label: "Contact", href: "/contact" },
    ],
  },
];

/**
 * A section's eyebrow, two-line heading and side blurb.
 *
 * @param eyebrow Small label above the heading.
 * @param title First heading line.
 * @param accent Second heading line, in the gradient.
 * @param blurb Supporting sentence beside the heading.
 * @returns The section header.
 */
function SectionHead({
  eyebrow,
  title,
  accent,
  blurb,
}: {
  eyebrow: string;
  title: string;
  accent: string;
  blurb: string;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-6">
      <div className="flex min-w-0 flex-[1_1_560px] flex-col gap-4.5">
        <p className="m-0 font-pixel text-sm tracking-[0.14em] text-(--chart-2) uppercase">
          {eyebrow}
        </p>
        <h2 className="m-0 font-pixel text-[clamp(2.2rem,4.6vw,4.2rem)] leading-[1.02] tracking-[-0.02em]">
          {title}
          <br />
          <span className="gradient-text">{accent}</span>
        </h2>
      </div>
      <p className="m-0 flex-[0_1_400px] text-[17px] leading-relaxed text-zinc-400">
        {blurb}
      </p>
    </div>
  );
}

/**
 * A bento feature card: numbered label, title, blurb and a demo.
 *
 * @param tag The `NN / WORD` label.
 * @param title The feature name.
 * @param body One-sentence description.
 * @param className Grid placement.
 * @param large Uses the larger title and the pink label.
 * @param children The card's demo.
 * @returns The card.
 */
function FeatureCard({
  tag,
  title,
  body,
  className = "",
  large = false,
  children,
}: {
  tag: string;
  title: string;
  body: string;
  className?: string;
  large?: boolean;
  children: React.ReactNode;
}) {
  return (
    <article
      className={`panel flex min-w-0 flex-col gap-4.5 overflow-hidden p-7 ${className}`}
    >
      <div className="flex flex-col gap-2">
        <p
          className={`m-0 font-pixel text-[13px] tracking-[0.12em] ${large ? "text-(--accent)" : "text-(--chart-2)"}`}
        >
          {tag}
        </p>
        <h3
          className={`m-0 font-pixel ${large ? "text-[30px]" : "text-[26px]"}`}
        >
          {title}
        </h3>
        <p className="m-0 max-w-130 text-[15px] leading-normal text-zinc-400">
          {body}
        </p>
      </div>
      {children}
    </article>
  );
}

/**
 * Renders the full landing page.
 *
 * A server component: the hero, copy and static cards render on the server,
 * and only the scripted demos and the two graphs hydrate.
 *
 * @returns Marketing homepage.
 */
export default function Home() {
  return (
    <div className="relative isolate">
      <SiteNavbar />

      <div className="relative overflow-hidden">
        <PixelGraph source="hero" followCursor />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_46%_40%_at_50%_47%,#09090be6_0%,#09090bb3_45%,#09090b00_100%)]"
        />

        <div className="relative flex min-h-dvh flex-col pt-16">
          <section className="flex grow flex-col items-center justify-center gap-7.5 px-5 pt-14 pb-12 text-center">
            <p className="m-0 font-pixel text-sm tracking-[0.14em] text-(--muted-foreground) uppercase">
              &gt; illume ingest github.com/your/repo
              <span className="caret text-(--accent)">_</span>
            </p>
            <h1 className="m-0 flex flex-col items-center gap-1.5 font-pixel leading-none">
              <span className="text-[calc((100vw-3rem)/4.75)] sm:text-[min(calc((100vw-3.5rem)/8.75),8.5rem)] tracking-[-0.02em] text-balance sm:whitespace-nowrap">
                Onboard engineers
              </span>
              <span className="gradient-text text-[calc((100vw-3rem)/4.75)] sm:text-[min(calc((100vw-3.5rem)/8.75),8.5rem)] tracking-[-0.02em] text-balance sm:whitespace-nowrap">
                in days, not weeks
              </span>
            </h1>
            <p className="m-0 max-w-160 text-[15px] leading-relaxed text-zinc-400 sm:text-[19px]">
              Point Illume at a GitHub repository. It maps every file into a
              living dependency graph, writes the{" "}
              <span className="text-(--foreground)">architecture brief</span>,
              the <span className="text-(--foreground)">reading order</span> and
              the <span className="text-(--foreground)">glossary</span>, then
              answers questions with sources you can check.
            </p>
            <div className="flex flex-wrap justify-center gap-3.5">
              <Link
                href="/login"
                className="cta inline-flex items-center gap-3 rounded-sm bg-(--primary) px-7 py-4 font-pixel text-[17px] tracking-[0.04em] text-(--primary-foreground)"
              >
                Get started <span aria-hidden="true">→</span>
              </Link>
              <a
                href="#tour"
                className="ghost inline-flex items-center gap-3 rounded-sm border border-(--border-strong) bg-(--background)/60 px-7 py-4 font-pixel text-[17px] tracking-[0.04em] text-zinc-300"
              >
                See it in action <span aria-hidden="true">↓</span>
              </a>
            </div>
          </section>
        </div>
      </div>

      <div className="bg-(--background)/80">
        <dl className="m-0 flex flex-wrap">
          {STATS.map(({ n, label, desc, tone }) => (
            <div
              key={n + label[0]}
              className="flex flex-[1_1_200px] flex-col gap-2 border-(--border) px-7 py-9 not-last:border-r"
            >
              <div className="flex items-baseline gap-3">
                <dd
                  className={`m-0 font-pixel text-[44px] leading-none ${tone ?? ""}`}
                >
                  {n}
                </dd>
                <dt className="text-xs tracking-[0.12em] text-zinc-300 uppercase">
                  {label[0]}
                  <br />
                  {label[1]}
                </dt>
              </div>
              <span className="text-[13px] leading-snug text-(--muted-foreground)">
                {desc}
              </span>
            </div>
          ))}
        </dl>
      </div>

      <section id="features" className="scroll-mt-16">
        <div className="mx-auto flex max-w-7xl flex-col gap-14 px-6 py-22.5">
          <SectionHead
            eyebrow="Features"
            title="Everything week one asks,"
            accent="answered on day one"
            blurb="One ingest turns a repository into a map, a guide and a teammate who has read every file, commit and pull request."
          />

          <div className="grid grid-cols-12 gap-4">
            <FeatureCard
              large
              tag="01 / ASK"
              title="Ask the codebase"
              body="Plain-English questions, answered from the code, commits, pull requests and docs, with every source attached so you can check it."
              className="col-span-12 lg:col-span-7 lg:row-span-2"
            >
              <AskDemo />
            </FeatureCard>

            <FeatureCard
              tag="02 / MAP"
              title="3D dependency graph"
              body="Every file and import, in a graph you can fly through. Click a file to see what it touches."
              className="col-span-12 lg:col-span-5"
            >
              <div
                aria-hidden="true"
                className="relative h-55 overflow-hidden rounded-sm border border-white/8 bg-(--background)"
              >
                <PixelGraph
                  source="sample"
                  spin
                  cell={3}
                  hubLabels={false}
                  focusLabel={false}
                  spreadY={0.42}
                  lightRadius={0.34}
                />
              </div>
            </FeatureCard>

            <FeatureCard
              tag="03 / PATH"
              title="Reading order"
              body="The order to read the code in, from foundations up, with a note on why each file matters."
              className="col-span-12 lg:col-span-5"
            >
              <ReadingOrderDemo />
            </FeatureCard>

            <FeatureCard
              tag="04 / BRIEF"
              title="Architecture brief"
              body="The stack, the entry points and how data flows, written up before you open a file."
              className="col-span-12 lg:col-span-4"
            >
              <BriefDemo />
            </FeatureCard>

            <FeatureCard
              tag="05 / WORDS"
              title="Codebase glossary"
              body="Every domain term and symbol in plain English, linked back to the code."
              className="col-span-12 lg:col-span-4"
            >
              <GlossaryDemo />
            </FeatureCard>

            <FeatureCard
              tag="06 / PEOPLE"
              title="Who to ask"
              body="Ownership for every file, mined from the last 500 commits."
              className="col-span-12 lg:col-span-4"
            >
              <div className="flex grow flex-col gap-3 rounded-sm border border-white/8 bg-(--background) p-4.5">
                <span className="font-pixel text-xs text-(--muted-foreground)">
                  services/rag.py
                </span>
                {OWNERS.map(([name, pct, color], i) => (
                  <div key={name} className="flex items-center gap-2.5">
                    <span className="w-26 shrink-0 truncate text-[13px] text-zinc-200">
                      {name}
                    </span>
                    <span className="h-2.5 grow bg-(--secondary)">
                      <span
                        className="bar-fill block h-2.5"
                        style={{
                          width: `${pct}%`,
                          background: color,
                          animationDelay: `${i * 0.3}s`,
                        }}
                      />
                    </span>
                    <span className="w-8 text-right font-pixel text-xs text-(--muted-foreground)">
                      {pct}%
                    </span>
                  </div>
                ))}
              </div>
            </FeatureCard>

            <FeatureCard
              tag="07 / FRESH"
              title="Keeps up with main"
              body="Turn on auto-update and the graph, guide and answers follow every merge, checked every 1 to 24 hours."
              className="col-span-12 lg:col-span-6"
            >
              <div className="flex flex-col gap-4 overflow-hidden rounded-sm border border-white/8 bg-(--background) py-4.5">
                <div aria-hidden="true" className="overflow-hidden">
                  <div className="marquee">
                    {[...COMMITS, ...COMMITS].map(([sha, msg], i) => (
                      <span
                        key={i}
                        className="flex shrink-0 items-center gap-2 border border-(--border) px-3 py-1.75 font-pixel text-xs whitespace-nowrap"
                      >
                        <span
                          className="h-1.5 w-1.5"
                          style={{
                            background: i % 3 === 0 ? "#f6339a" : "#00b8db",
                          }}
                        />
                        <span className="text-(--muted-foreground)">{sha}</span>
                        {msg}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="flex items-center gap-2.5 px-4.5 font-pixel text-[13px] text-zinc-300">
                  <span className="blink h-2 w-2 bg-(--chart-1)" />
                  Up to date with main · next check in 6h
                </div>
              </div>
            </FeatureCard>

            <FeatureCard
              tag="08 / EDITOR"
              title="In your editor, over MCP"
              body="Connect Claude Code, Cursor or any MCP client, so the agent in your editor knows the codebase too."
              className="col-span-12 lg:col-span-6"
            >
              <McpDemo />
            </FeatureCard>
          </div>
        </div>
      </section>

      <section id="how-it-works" className="scroll-mt-16">
        <div className="mx-auto flex max-w-7xl flex-col gap-12 px-6 py-22.5">
          <SectionHead
            eyebrow="How it works"
            title="From git clone"
            accent="to “I get it”"
            blurb="One link in. A map, a guide and a teammate who has read everything out, in four steps."
          />
          <HowItWorks />
        </div>
      </section>

      <section id="tour" className="scroll-mt-16">
        <div className="mx-auto flex max-w-7xl flex-col gap-10 px-6 py-22.5">
          <SectionHead
            eyebrow="The tour"
            title="Five minutes,"
            accent="one whole repo"
            blurb="Watch Illume take a real codebase from a link to a guide, start to finish. Jump to the part you care about."
          />
          <Tour />
        </div>
      </section>

      <section id="faq" className="scroll-mt-16">
        <div className="mx-auto max-w-7xl px-6 py-22.5">
          <Faq />
        </div>
      </section>

      <section id="start" className="relative scroll-mt-16 overflow-hidden">
        <EndCta />
      </section>

      <footer className="relative border-t border-(--border) bg-(--background)/80">
        <div className="mx-auto flex max-w-7xl flex-col gap-12 px-6 pt-12 pb-8">
          <div className="grid grid-cols-2 gap-8 md:grid-cols-[minmax(0,2fr)_repeat(3,minmax(0,1fr))]">
            <div className="col-span-2 flex min-w-0 flex-col gap-4 md:col-span-1">
              <Link
                href="/"
                aria-label="Illume home"
                className="flex items-center gap-2.5"
              >
                <Logo size={34} />
                <span className="font-pixel text-2xl">illume</span>
              </Link>
              <p className="m-0 max-w-80 text-[15px] leading-relaxed text-(--muted-foreground)">
                Onboard engineers in days, not weeks.
              </p>
              <SystemStatus />
            </div>
            {FOOTER_COLUMNS.map((col) => (
              <nav
                key={col.title}
                aria-label={col.title}
                className="flex min-w-0 flex-col gap-3"
              >
                <p className="eyebrow m-0 mb-1">{col.title}</p>
                {col.links.map((link) =>
                  link.external ? (
                    <a
                      key={link.label}
                      href={link.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[15px] text-zinc-300 hover:text-(--accent)"
                    >
                      {link.label}
                    </a>
                  ) : (
                    <Link
                      key={link.label}
                      href={link.href}
                      className="text-[15px] text-zinc-300 hover:text-(--accent)"
                    >
                      {link.label}
                    </Link>
                  ),
                )}
              </nav>
            ))}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-4 border-t border-white/8 pt-6 font-pixel text-xs tracking-[0.08em] text-(--subtle-foreground) uppercase">
            <span>© {new Date().getFullYear()} Illume</span>
            <span className="flex flex-wrap items-center gap-4">
              Built by <span className="text-(--foreground)">Tejas Nasa</span>
              <a
                href="https://github.com/tejasnasa"
                target="_blank"
                rel="noopener noreferrer"
                className="text-zinc-300 hover:text-(--accent)"
              >
                GitHub ↗
              </a>
              <a
                href="https://tejasnasa.me"
                target="_blank"
                rel="noopener noreferrer"
                className="text-zinc-300 hover:text-(--accent)"
              >
                tejasnasa.me ↗
              </a>
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}
