import { StarFourIcon } from "@phosphor-icons/react/dist/ssr";

export default function Home() {
  return (
    <div className="relative min-h-screen w-full">
      {/* ── Background decorations ── */}
      <div className="fixed inset-0 z-0 pointer-events-none overflow-hidden">
        <div className="orb orb-1" />
        <div className="orb orb-2" />
        <div className="orb orb-3" />
      </div>
      <div className="fixed inset-0 z-0 pointer-events-none" />

      {/* ── Content wrapper ── */}
      <div className="relative z-10">
        {/* ═══ NAVBAR ═══ */}
        <nav className="fixed top-0 inset-x-0 z-50 backdrop-blur-xl">
          <div className="max-w-[1200px] mx-auto px-6 h-16 flex items-center justify-between">
            <div className="relative">
              <div className="absolute inset-0 blur-xl bg-(--chart-1)/30 rounded-full" />

              <StarFourIcon
                className="relative text-(--chart-1)"
                weight="fill"
                size={36}
              />
            </div>
            <div className="flex items-center gap-6">
              <a
                href="#features"
                className="text-sm text-(--muted-foreground) hover:text-(--foreground) transition-colors hidden sm:block"
              >
                Features
              </a>
              <a
                href="#tech"
                className="text-sm text-(--muted-foreground) hover:text-(--foreground) transition-colors hidden sm:block"
              >
                Stack
              </a>
              <a
                href="#architecture"
                className="text-sm text-(--muted-foreground) hover:text-(--foreground) transition-colors hidden sm:block"
              >
                Architecture
              </a>
              <a
                href="https://github.com/tejasnasa/illume"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-full border border-(--foreground)/10 text-(--muted-foreground) hover:text-(--foreground) hover:border-(--primary)/40 transition-all"
              >
                <GithubIcon />
                GitHub
              </a>
            </div>
          </div>
        </nav>

        {/* ═══ HERO ═══ */}
        <section className="relative min-h-screen flex flex-col items-center justify-center px-6 pt-24 pb-16 text-center">
          {/* Badge */}
          <div className="fade-up fd1">
            <div className="shimmer-badge inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-amber-500/20 bg-amber-500/[0.06] mb-8">
              <span className="pulse-dot w-2 h-2 rounded-full bg-amber-400 inline-block" />
              <span className="text-xs font-medium text-amber-300 tracking-widest uppercase">
                Preview · Under Active Development
              </span>
            </div>
          </div>

          {/* Heading */}
          <h1 className="fade-up fd2 max-w-4xl">
            <span className="block text-[clamp(40px,6vw,72px)] font-bold tracking-tighter text-(--foreground) leading-[1.1]">
              Understand any
            </span>
            <span className="gradient-text block text-[clamp(40px,6vw,72px)] font-bold tracking-tighter leading-[1.1] mt-2">
              codebase instantly
            </span>
          </h1>

          {/* Subtitle */}
          <p className="fade-up fd3 mt-6 text-lg sm:text-xl text-(--muted-foreground) max-w-2xl leading-relaxed">
            AI-powered repo analysis with a deterministic{" "}
            <span className="text-(--chart-1) font-medium">AST-first</span>{" "}
            approach — hallucination-free querying and{" "}
            <span className="text-(--primary) font-medium">
              3D architectural
            </span>{" "}
            visualization.
          </p>

          {/* CTAs */}
          <div className="fade-up fd4 flex flex-col sm:flex-row gap-4 mt-10">
            <a
              href="https://github.com/tejasnasa/illume"
              target="_blank"
              rel="noopener noreferrer"
              className="cta-glow inline-flex items-center justify-center gap-2 px-8 py-3.5 rounded-full bg-linear-to-r from-(--primary) to-(--accent) text-(--foreground) font-medium text-sm"
            >
              <GithubIcon />
              View on GitHub
            </a>
            <a
              href="#features"
              className="inline-flex items-center justify-center gap-2 px-8 py-3.5 rounded-full border border-(--foreground)/10 text-(--muted-foreground) font-medium text-sm hover:border-(--primary)/30 hover:text-(--foreground) transition-all"
            >
              Explore Features
              <svg
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M19 9l-7 7-7-7"
                />
              </svg>
            </a>
          </div>

          {/* Version */}
          <div className="fade-up fd5 mt-16 flex items-center gap-3 text-sm text-zinc-600">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
              <span className="w-1.5 h-1.5 rounded-full bg-zinc-700" />
            </div>
            <span>v0.1.0 · AST Engine &amp; RAG pipeline in progress</span>
          </div>

          {/* Scroll indicator */}
          <div className="absolute bottom-10 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2 text-(--muted-foreground)">
            <span className="text-[10px] tracking-[0.15em] uppercase">
              Scroll
            </span>
            <div className="w-5 h-8 rounded-full border border-zinc-700 flex justify-center pt-1.5">
              <div className="scroll-bounce w-[3px] h-2 rounded-full bg-(--muted-foreground)" />
            </div>
          </div>
        </section>

        {/* ── Divider ── */}
        <div className="glow-line max-w-3xl mx-auto" />

        {/* ═══ FEATURES ═══ */}
        <section id="features" className="py-32 px-6 max-w-[1200px] mx-auto">
          <div className="text-center mb-20">
            <span className="block text-xs font-semibold tracking-[0.2em] uppercase text-(--primary) mb-4">
              Capabilities
            </span>
            <h2 className="text-4xl sm:text-5xl font-bold text-(--foreground) tracking-tight">
              Engineered for <span className="gradient-text">precision</span>
            </h2>
            <p className="mt-4 text-lg text-(--muted-foreground) max-w-xl mx-auto">
              No guesswork. No hallucinations. Just deterministic, structural
              code intelligence.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <FeatureCard
              emoji="🌳"
              color="violet"
              title="Deterministic AST Engine"
              description="Tree-Sitter powered structural parsing — not string-dumping into LLM context windows. Accurate extraction of functions, classes, and call relationships."
              tags={["Tree-Sitter", "AST Traversal", "Call Graphs"]}
              float="float-subtle"
            />
            <FeatureCard
              emoji="🔎"
              color="cyan"
              title="Intelligent RAG Architecture"
              description="Semantic vector embeddings tied to AST blocks via pgvector foreign keys. Hyper-specific search that maps to actual code logic — no generic LLM guessing."
              tags={["pgvector", "Embeddings", "Semantic Search"]}
              float="float-subtle-d"
            />
            <FeatureCard
              emoji="🌐"
              color="rose"
              title="3D Dependency Visualization"
              description="Interactive force-graph rendering that plots complex import webs and circular dependencies for repos exceeding 10,000+ nodes. Real-time WebSocket telemetry."
              tags={["Force Graph 3D", "WebSockets", "Live Telemetry"]}
              float="float-subtle"
            />
            <FeatureCard
              emoji="🧬"
              color="emerald"
              title="Code Health Metrics"
              description="Automated scoring computed natively — lines of code, cyclomatic complexity, and coupling heatmaps derived before any LLM is ever contacted."
              tags={["LOC Analysis", "Complexity", "Coupling Maps"]}
              float="float-subtle-d"
            />
          </div>
        </section>

        {/* ── Divider ── */}
        <div className="glow-line max-w-3xl mx-auto" />

        {/* ═══ ARCHITECTURE ═══ */}
        <section
          id="architecture"
          className="py-32 px-6 max-w-[1000px] mx-auto"
        >
          <div className="text-center mb-16">
            <span className="block text-xs font-semibold tracking-[0.2em] uppercase text-(--destructive) mb-4">
              Architecture
            </span>
            <h2 className="text-4xl sm:text-5xl font-bold text-(--foreground) tracking-tight">
              How it <span className="gradient-text">works</span>
            </h2>
            <p className="mt-4 text-lg text-(--muted-foreground) max-w-xl mx-auto">
              From GitHub URL to queryable, visualized code intelligence.
            </p>
          </div>

          <div className="glass-card rounded-2xl p-8 sm:p-12">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-8">
              <ArchStep
                emoji="📥"
                colorClass="bg-(--primary)/10 border-(--primary)/20"
                step="1"
                title="Ingest"
                desc="Submit a GitHub URL. Celery workers clone the repo via a Redis-brokered task queue."
              />
              <ArchStep
                emoji="🌳"
                colorClass="bg-(--accent)/10 border-(--accent)/20"
                step="2"
                title="Parse"
                desc="Tree-Sitter traverses the AST. Functions, classes, and calls are extracted deterministically."
              />
              <ArchStep
                emoji="🧠"
                colorClass="bg-(--accent)/10 border-(--accent)/20"
                step="3"
                title="Embed & Query"
                desc="Code blocks become vector embeddings in pgvector. Ask anything — get pinpoint-accurate answers."
              />
            </div>

            <div className="mt-10 pt-6 border-t border-(--foreground)/[0.04] flex flex-wrap justify-center gap-6 text-xs text-(--muted-foreground)">
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-(--primary)" />
                FastAPI
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                Redis
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-(--accent)" />
                Celery
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
                PostgreSQL + pgvector
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-white" />
                Next.js
              </span>
            </div>
          </div>
        </section>

        {/* ── Divider ── */}
        <div className="glow-line max-w-3xl mx-auto" />

        {/* ═══ DEVELOPMENT STATUS ═══ */}
        <section className="py-32 px-6 max-w-[800px] mx-auto text-center">
          <div className="shimmer-badge inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-amber-500/20 bg-amber-500/[0.06] mb-8">
            <span className="pulse-dot w-2 h-2 rounded-full bg-amber-400 inline-block" />
            <span className="text-xs font-medium text-amber-300 tracking-widest uppercase">
              Development Preview
            </span>
          </div>

          <h2 className="text-3xl sm:text-4xl font-bold text-white tracking-tight mb-6">
            Currently in early access
          </h2>
          <p className="text-lg text-zinc-500 leading-relaxed max-w-xl mx-auto mb-12">
            Illume is actively being built in the open. Core systems are under
            development — star the repo to follow progress and get notified when
            we ship.
          </p>

          {/* Roadmap */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-left mb-12">
            <div className="glass-card rounded-xl p-5">
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2 h-2 rounded-full bg-emerald-400" />
                <span className="text-[11px] font-semibold text-emerald-400 uppercase tracking-wider">
                  In Progress
                </span>
              </div>
              <p className="text-sm text-zinc-300">
                AST engine &amp; Tree-Sitter integration
              </p>
            </div>
            <div className="glass-card rounded-xl p-5">
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2 h-2 rounded-full bg-amber-400" />
                <span className="text-[11px] font-semibold text-amber-400 uppercase tracking-wider">
                  Planned
                </span>
              </div>
              <p className="text-sm text-zinc-300">
                RAG pipeline &amp; vector embeddings
              </p>
            </div>
            <div className="glass-card rounded-xl p-5">
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2 h-2 rounded-full bg-zinc-600" />
                <span className="text-[11px] font-semibold text-zinc-500 uppercase tracking-wider">
                  Upcoming
                </span>
              </div>
              <p className="text-sm text-zinc-300">
                3D visualization &amp; chat interface
              </p>
            </div>
          </div>

          <a
            href="https://github.com/tejasnasa/illume"
            target="_blank"
            rel="noopener noreferrer"
            className="cta-glow inline-flex items-center gap-2.5 px-8 py-3.5 rounded-full bg-gradient-to-r from-violet-600 to-(--primary) text-white font-medium text-sm"
          >
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 .587l3.668 7.568 8.332 1.151-6.064 5.828 1.48 8.279-7.416-3.967-7.417 3.967 1.481-8.279-6.064-5.828 8.332-1.151z" />
            </svg>
            Star on GitHub
          </a>
        </section>

        {/* ═══ FOOTER ═══ */}
        <footer className="border-t border-(--foreground)/[0.04] py-10 px-6">
          <div className="max-w-[1200px] mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-2.5">
              <div className="w-6 h-6 rounded-md bg-gradient-to-br from-(--primary) to-(--accent) flex items-center justify-center text-white text-[10px] font-bold">
                ✦
              </div>
              <span className="text-sm text-zinc-600">
                Illume · Built by{" "}
                <a
                  href="https://github.com/tejasnasa"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-zinc-400 hover:text-(--foreground) transition-colors"
                >
                  Tejas
                </a>
              </span>
            </div>
            <div className="flex items-center gap-2 text-xs text-zinc-700">
              <span className="pulse-dot w-1.5 h-1.5 rounded-full bg-amber-500 inline-block" />
              Pre-release · v0.1.0-alpha
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
}

/* ═══ COMPONENTS ═══ */

const COLOR_MAP: Record<string, { icon: string; tag: string }> = {
  violet: {
    icon: "bg-(--primary)/10 border border-(--primary)/20",
    tag: "bg-(--primary)/10 text-(--primary) border border-(--primary)/20",
  },
  cyan: {
    icon: "bg-(--accent)/10 border border-(--accent)/20",
    tag: "bg-(--accent)/10 text-(--accent) border border-(--accent)/20",
  },
  rose: {
    icon: "bg-rose-500/10 border border-rose-500/20",
    tag: "bg-rose-500/10 text-rose-400 border border-rose-500/20",
  },
  emerald: {
    icon: "bg-emerald-500/10 border border-emerald-500/20",
    tag: "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20",
  },
};

function FeatureCard({
  emoji,
  color,
  title,
  description,
  tags,
  float,
}: {
  emoji: string;
  color: string;
  title: string;
  description: string;
  tags: string[];
  float: string;
}) {
  const c = COLOR_MAP[color] ?? COLOR_MAP.violet;
  return (
    <div className="glass-card rounded-2xl p-8">
      <div
        className={`${float} w-12 h-12 rounded-xl ${c.icon} flex items-center justify-center text-2xl mb-6`}
      >
        {emoji}
      </div>
      <h3 className="text-xl font-semibold text-(--foreground) mb-3">
        {title}
      </h3>
      <p className="text-[15px] text-(--mute-foreground) leading-relaxed mb-4">
        {description}
      </p>
      <div className="flex flex-wrap gap-2">
        {tags.map((tag) => (
          <span
            key={tag}
            className={`text-xs px-2.5 py-1 rounded-full ${c.tag}`}
          >
            {tag}
          </span>
        ))}
      </div>
    </div>
  );
}

function ArchStep({
  emoji,
  colorClass,
  step,
  title,
  desc,
}: {
  emoji: string;
  colorClass: string;
  step: string;
  title: string;
  desc: string;
}) {
  return (
    <div className="text-center">
      <div
        className={`node-glow w-16 h-16 rounded-2xl ${colorClass} border flex items-center justify-center text-[28px] mx-auto mb-4`}
      >
        {emoji}
      </div>
      <h4 className="text-sm font-semibold text-white mb-1">
        {step}. {title}
      </h4>
      <p className="text-[13px] text-zinc-500 leading-relaxed max-w-[240px] mx-auto">
        {desc}
      </p>
    </div>
  );
}

function GithubIcon() {
  return (
    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
    </svg>
  );
}
