"use client";

import dashboard from "@/assets/dashboard.png";
import explorer from "@/assets/explorer.png";
import graph from "@/assets/graph.png";
import {
  ArrowDownIcon,
  ArrowRightIcon,
  BrainIcon,
  ChatTeardropTextIcon,
  GitBranchIcon,
  GithubLogoIcon,
  LinkedinLogoIcon,
  ListChecksIcon,
  MagnifyingGlassIcon,
  MapTrifoldIcon,
  PulseIcon,
  SparkleIcon,
  StarFourIcon,
  TreeStructureIcon,
  UsersFourIcon,
  WarningDiamondIcon,
  XLogoIcon,
} from "@phosphor-icons/react/dist/ssr";
import { motion, type Variants } from "motion/react";
import Image from "next/image";
import Link from "next/link";

const fadeUp: Variants = {
  hidden: { opacity: 0, y: 32 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: {
      delay: i * 0.1,
      duration: 0.6,
      ease: [0.25, 0.46, 0.45, 0.94],
    },
  }),
};

const stagger = {
  visible: { transition: { staggerChildren: 0.08 } },
};

const FEATURES = [
  {
    icon: MapTrifoldIcon,
    title: "Architecture Brief",
    description:
      "Auto-generated executive summaries — detects tech stacks, maps entry points, and traces data flows through your codebase.",
    color: "oklch(0.6270 0.2148 292.72)",
  },
  {
    icon: ListChecksIcon,
    title: "Guided Reading Order",
    description:
      "Topologically sorted learning paths. Know exactly where to start and what to read next with LLM-annotated explanations.",
    color: "var(--chart-1)",
  },
  {
    icon: MagnifyingGlassIcon,
    title: "Codebase Glossary",
    description:
      "Every function, class, and domain term explained in plain English. Searchable, browsable, and linked to source code.",
    color: "oklch(0.7225 0.1768 149.58)",
  },
  {
    icon: UsersFourIcon,
    title: "Code Ownership Map",
    description:
      "Who wrote what, who owns what, who to ask. Knowledge silo detection with bus-factor analysis from git history.",
    color: "var(--destructive)",
  },
  {
    icon: WarningDiamondIcon,
    title: "Critical File Guardrails",
    description:
      "Traffic-light tagging: 🔴 Critical 🟡 Caution 🟢 Safe. Know what you can touch and what needs review.",
    color: "oklch(0.7954 0.1758 85.87)",
  },
  {
    icon: ChatTeardropTextIcon,
    title: "Ask the Codebase",
    description:
      "RAG-powered Q&A over code, commits, and pull requests. Ask 'why' — get answers citing the exact PR that made the change.",
    color: "var(--sidebar-primary)",
  },
];

const PIPELINE_STEPS = [
  {
    icon: GitBranchIcon,
    label: "Clone & Analyze",
    desc: "Full git clone with history. Extract commits, PRs, and ownership data.",
  },
  {
    icon: TreeStructureIcon,
    label: "Parse AST",
    desc: "Tree-sitter extracts functions, classes, imports, and dependency edges.",
  },
  {
    icon: BrainIcon,
    label: "Embed & Generate",
    desc: "OpenAI embeddings for RAG. LLM generates glossary, brief, and reading order.",
  },
  {
    icon: SparkleIcon,
    label: "Onboarding Ready",
    desc: "Interactive guide with architecture brief, ownership map, and 3D graph.",
  },
];

export default function Home() {
  return (
    <main className="relative">
      <div className="fixed inset-0 -z-10 pointer-events-none overflow-hidden">
        <motion.div
          animate={{ x: [0, 40, -20, 0], y: [0, -30, 15, 0] }}
          transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }}
          className="absolute -top-40 -left-40 w-150 h-150 rounded-full bg-(--primary) opacity-[0.11] blur-[120px]"
        />
        <motion.div
          animate={{ x: [0, -25, 35, 0], y: [0, 40, -20, 0] }}
          transition={{
            duration: 15,
            repeat: Infinity,
            ease: "easeInOut",
            delay: 2,
          }}
          className="absolute top-1/3 -right-40 w-125 h-125 rounded-full bg-(--chart-1) opacity-[0.07] blur-[120px]"
        />
        <motion.div
          animate={{ x: [0, 30, -15, 0], y: [0, -25, 30, 0] }}
          transition={{
            duration: 18,
            repeat: Infinity,
            ease: "easeInOut",
            delay: 4,
          }}
          className="absolute -bottom-40 left-1/3 w-100 h-100 rounded-full bg-(--chart-2) opacity-[0.07] blur-[120px]"
        />
      </div>

      <nav className="fixed top-0 inset-x-0 z-50 backdrop-blur-xl border-b border-(--border)">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link
            href={"/"}
            className="relative h-12 flex items-center justify-center m-2 gap-2"
          >
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="h-10 w-40 rounded-full bg-(--chart-1)/30 blur-xl" />
            </div>
            <StarFourIcon
              className="relative text-(--chart-1)"
              weight="fill"
              size={24}
            />
            <span className="text-xl font-semibold">Illume</span>
          </Link>

          <div className="flex items-center gap-1">
            {["Features", "How It Works"].map((item) => (
              <a
                key={item}
                href={`#${item.toLowerCase().replace(/\s+/g, "-")}`}
                className="hidden sm:block px-4 py-2 text-sm text-(--muted-foreground) hover:text-(--foreground) rounded-lg hover:bg-(--secondary) transition-all duration-200"
              >
                {item}
              </a>
            ))}
            {/* <Link
              href="/login"
              className="ml-2 flex items-center gap-2 px-5 py-2 text-sm rounded-full border border-(--primary) text-(--muted-foreground) hover:text-(--foreground) hover:border-(--primary) transition-all duration-200"
            >
              <span className="hidden sm:inline">Login</span>
            </Link> */}
            <Link
              href="/login"
              className="ml-2 flex items-center gap-2 px-4 py-2 text-sm rounded-full border bg-(--primary) border-(--border)  hover:border-white transition-all duration-200"
            >
              <span className="sm:inline">Login</span>
            </Link>
          </div>
        </div>
      </nav>

      <section className="relative min-h-screen flex flex-col items-center justify-center px-6 pt-36 pb-20 text-center overflow-hidden">
        <motion.div
          initial="hidden"
          animate="visible"
          variants={stagger}
          className="flex flex-col items-center"
        >
          <motion.div variants={fadeUp} custom={0}>
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-(--chart-1)/20 bg-(--chart-1)/6 mb-6">
              <PulseIcon
                size={14}
                className="text-(--chart-1) animate-pulse"
                weight="bold"
              />
              <span className="text-xs font-medium text-(--chart-1) tracking-widest uppercase">
                AI-Powered Onboarding Platform
              </span>
            </div>
          </motion.div>

          <motion.h1 variants={fadeUp} custom={1} className="max-w-6xl">
            <span className="block text-[clamp(3rem,6vw,7rem)] font-bold tracking-tighter text-(--foreground) leading-[1.1]">
              Onboard engineers
            </span>
            <span className="block text-[clamp(3rem,6vw,7rem)] font-bold tracking-tighter leading-[1.1] mt-1 gradient-text">
              in days, not weeks
            </span>
          </motion.h1>

          <motion.p
            variants={fadeUp}
            custom={2}
            className="mt-6 text-md sm:text-xl text-(--muted-foreground) max-w-2xl leading-relaxed"
          >
            Illume ingests a GitHub repository and generates an{" "}
            <span className="text-(--foreground) font-medium">
              interactive onboarding guide
            </span>{" "}
            — architecture briefs, reading orders, glossaries, and ownership
            maps.{" "}
            <span className="text-(--primary) font-medium">All automated.</span>
          </motion.p>

          <motion.div
            variants={fadeUp}
            custom={3}
            className="flex flex-col sm:flex-row gap-4 mt-10"
          >
            <Link
              href="/login"
              className="group inline-flex items-center justify-center gap-2 px-8 py-3.5 rounded-full bg-(--primary) text-(--primary-foreground) font-medium text-md hover:brightness-110 hover:-translate-y-0.5 transition-all duration-300"
            >
              Get Started
              <ArrowRightIcon
                size={16}
                weight="bold"
                className="group-hover:translate-x-0.5 transition-transform"
              />
            </Link>
            <a
              href="#preview"
              className="inline-flex items-center justify-center gap-2 px-8 py-3.5 rounded-full border border-(--border) text-(--muted-foreground) font-medium text-md hover:border-(--primary) hover:text-(--foreground) transition-all duration-300"
            >
              See It In Action
              <ArrowDownIcon size={16} weight="bold" />
            </a>
          </motion.div>

          <motion.div
            variants={fadeUp}
            custom={4}
            className="mt-14 flex items-center gap-8 text-md text-(--muted-foreground)"
          >
            <div className="flex flex-col items-center gap-1">
              <span className="text-3xl font-bold text-(--foreground)">9</span>
              <span className="text-sm">Features</span>
            </div>
            <div className="w-px h-8 bg-(--border)" />
            <div className="flex flex-col items-center gap-1">
              <span className="text-3xl font-bold text-(--foreground)">6</span>
              <span className="text-sm">AI Pipelines</span>
            </div>
            <div className="w-px h-8 bg-(--border)" />
            <div className="flex flex-col items-center gap-1">
              <span className="text-3xl font-bold text-(--foreground)">3D</span>
              <span className="text-sm">Graph View</span>
            </div>
          </motion.div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.2 }}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2"
        >
          <span className="text-[10px] tracking-[0.2em] uppercase text-(--muted-foreground)">
            Scroll
          </span>
          <ArrowDownIcon
            size={16}
            className="text-(--muted-foreground) animate-bounce"
          />
        </motion.div>
      </section>

      <div className="max-w-3xl mx-auto h-px bg-linear-to-r from-transparent via-(--primary)/30 to-transparent" />

      <section id="features" className="py-28 px-6 max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.5 }}
          className="text-center"
        >
          <span className="inline-block text-xs font-semibold tracking-[0.2em] uppercase text-(--primary) mb-4">
            Features
          </span>
          <h2 className="text-3xl sm:text-5xl font-bold text-(--foreground) tracking-tight">
            Everything a new hire needs
          </h2>
          <p className="mt-4 text-lg text-(--muted-foreground) max-w-xl mx-auto">
            From architecture overview to code ownership — generated
            automatically from your repository.
          </p>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 mt-16">
          {FEATURES.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 24 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ delay: i * 0.08, duration: 0.5 }}
              whileHover={{ rotateX: 4, rotateY: -4, scale: 1.02 }}
              style={{ transformPerspective: 800 }}
            >
              <div className="group relative h-full rounded-2xl border border-(--border) bg-(--card)/40 backdrop-blur-sm p-7 hover:border-(--primary)/40 hover:-translate-y-1 transition-all duration-300">
                <div
                  className="w-11 h-11 rounded-xl flex items-center justify-center mb-5"
                  style={{
                    backgroundColor: `color-mix(in oklch, ${f.color} 12%, transparent)`,
                    border: `1px solid color-mix(in oklch, ${f.color} 20%, transparent)`,
                  }}
                >
                  <f.icon
                    size={22}
                    weight="duotone"
                    style={{ color: f.color }}
                  />
                </div>

                <h3 className="font-semibold text-(--foreground) mb-2 text-xl">
                  {f.title}
                </h3>
                <p className="text-sm text-(--muted-foreground) leading-relaxed">
                  {f.description}
                </p>
              </div>
            </motion.div>
          ))}
        </div>
      </section>

      <div className="max-w-3xl mx-auto h-px bg-linear-to-r from-transparent via-(--primary)/30 to-transparent" />

      <section id="how-it-works" className="py-28 px-6 max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.5 }}
          className="text-center"
        >
          <span className="inline-block text-xs font-semibold tracking-[0.2em] uppercase text-(--primary) mb-4">
            How It Works
          </span>
          <h2 className="text-3xl sm:text-5xl font-bold text-(--foreground) tracking-tight">
            From GitHub URL to onboarding guide
          </h2>
          <p className="mt-4 text-lg text-(--muted-foreground) max-w-xl mx-auto">
            Submit a repository. Get a living document in minutes.
          </p>
        </motion.div>

        <div className="mt-16 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 relative">
          {PIPELINE_STEPS.map((step, i) => (
            <motion.div
              key={step.label}
              initial={{ opacity: 0, y: 24 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-40px" }}
              transition={{ delay: i * 0.12, duration: 0.5 }}
              className="relative flex flex-col items-center text-center"
            >
              <div className="relative mb-5">
                <div className="w-17 h-17 rounded-2xl border border-(--border) bg-(--card) flex items-center justify-center group hover:border-(--primary)/50 transition-colors duration-300">
                  <step.icon
                    size={28}
                    weight="duotone"
                    className="text-(--primary)"
                  />
                </div>
                <div className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-(--primary) text-(--primary-foreground) text-xs font-bold flex items-center justify-center">
                  {i + 1}
                </div>
              </div>

              <h4 className="text-lg font-semibold text-(--foreground) mb-1.5">
                {step.label}
              </h4>
              <p className="text-sm text-(--muted-foreground) leading-relaxed max-w-55">
                {step.desc}
              </p>
            </motion.div>
          ))}
        </div>
      </section>

      <div className="max-w-3xl mx-auto h-px bg-linear-to-r from-transparent via-(--primary)/30 to-transparent" />

      <section className="py-28 px-6 max-w-7xl mx-auto" id="preview">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.5 }}
          className="text-center"
        >
          <span className="inline-block text-xs font-semibold tracking-[0.2em] uppercase text-(--primary) mb-4">
            Preview
          </span>
          <h2 className="text-3xl sm:text-5xl font-bold text-(--foreground) tracking-tight">
            See it in action
          </h2>
          <p className="mt-4 text-lg text-(--muted-foreground) max-w-xl mx-auto">
            Interactive onboarding guides generated from real repositories.
          </p>
        </motion.div>

        <div className="mt-16 grid grid-cols-1 lg:grid-cols-2 gap-6">
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6 }}
            className="lg:col-span-2 rounded-2xl border border-(--border) bg-(--card)/40 overflow-hidden"
          >
            <div className="px-6 py-4 border-b border-(--border) flex items-center gap-2">
              <div className="flex gap-1.5">
                <span className="w-3 h-3 rounded-full bg-red-500/60" />
                <span className="w-3 h-3 rounded-full bg-yellow-500/60" />
                <span className="w-3 h-3 rounded-full bg-green-500/60" />
              </div>
              <span className="ml-3 text-xs text-(--muted-foreground)">
                Dashboard
              </span>
            </div>
            <div className="aspect-21/9 bg-(--secondary)/40 flex items-center justify-center">
              <Image
                src={dashboard}
                alt="Dashboard Screenshot"
                className="object-cover"
              />
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 24 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.1, duration: 0.5 }}
            className="rounded-2xl border border-(--border) bg-(--card)/40 overflow-hidden"
          >
            <div className="px-4 py-3 border-b border-(--border) flex items-center gap-2">
              <div className="flex gap-1.5">
                <span className="w-3 h-3 rounded-full bg-red-500/60" />
                <span className="w-3 h-3 rounded-full bg-yellow-500/60" />
                <span className="w-3 h-3 rounded-full bg-green-500/60" />
              </div>
              <span className="ml-3 text-xs text-(--muted-foreground)">
                3D Dependency Graph
              </span>
            </div>
            <div className="aspect-video bg-(--secondary)/40 flex items-center justify-center">
              <Image
                src={graph}
                alt="3D Dependency Graph Screenshot"
                className="object-cover"
              />
            </div>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.2, duration: 0.5 }}
            className="rounded-2xl border border-(--border) bg-(--card)/40 overflow-hidden"
          >
            <div className="px-4 py-3 border-b border-(--border) flex items-center gap-2">
              <div className="flex gap-1.5">
                <span className="w-3 h-3 rounded-full bg-red-500/60" />
                <span className="w-3 h-3 rounded-full bg-yellow-500/60" />
                <span className="w-3 h-3 rounded-full bg-green-500/60" />
              </div>
              <span className="ml-3 text-xs text-(--muted-foreground)">
                Explorer Interface
              </span>
            </div>
            <div className="aspect-video bg-(--secondary)/40 flex items-center justify-center">
              <Image
                src={explorer}
                alt="RAG Chat Interface Screenshot"
                className="object-cover"
              />
            </div>
          </motion.div>
        </div>
      </section>

      <div className="max-w-3xl mx-auto h-px bg-linear-to-r from-transparent via-(--primary)/30 to-transparent" />

      <section className="py-24 px-12">
        <motion.div
          initial={{ opacity: 0, y: 32 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="max-w-3xl mx-auto text-center"
        >
          <div className="p-8 sm:p-10 relative overflow-hidden">
            <div className="relative">
              <h2 className="text-3xl sm:text-4xl font-bold text-(--foreground) tracking-tight my-4">
                Ready to <span className="gradient-text">illuminate</span> your
                codebase?
              </h2>
              <p className="text-(--muted-foreground) text-md mb-10 max-w-lg mx-auto">
                Submit a repository and get a complete onboarding guide
                generated in minutes.
              </p>
              <div className="flex flex-col sm:flex-row gap-4 justify-center">
                <Link
                  href="/login"
                  className="group inline-flex items-center justify-center gap-2 px-8 py-3.5 rounded-full bg-(--primary) text-(--primary-foreground) font-medium text-sm hover:brightness-110 hover:-translate-y-0.5 transition-all duration-300"
                >
                  Start Analyzing
                  <ArrowRightIcon
                    size={16}
                    weight="bold"
                    className="group-hover:translate-x-0.5 transition-transform"
                  />
                </Link>
                <a
                  href="https://github.com/tejasnasa/illume"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center justify-center gap-2 px-8 py-3.5 rounded-full border border-(--border) text-(--muted-foreground) font-medium text-sm hover:border-(--primary) hover:text-(--foreground) transition-all duration-300"
                >
                  <GithubLogoIcon size={16} weight="bold" />
                  Star on GitHub
                </a>
              </div>
            </div>
          </div>
        </motion.div>
      </section>

      <footer className="border-t border-(--border) pt-3 pb-6 px-6">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <div className="relative h-12 w-12 flex items-center justify-center">
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="h-10 w-10 rounded-full bg-(--chart-1)/30 blur-xl" />
              </div>
              <StarFourIcon
                className="relative text-(--chart-1)"
                weight="fill"
                size={24}
              />
            </div>
            <span className="text-sm text-(--muted-foreground)">
              Illume &middot; Built by Tejas Nasa
            </span>
          </div>
          <div className="flex items-center gap-4 text-2xl text-(--muted-foreground)">
            <a
              href="https://github.com/tejasnasa"
              target="_blank"
              className="hover:text-(--foreground) transition-colors"
            >
              <GithubLogoIcon />
            </a>
            <a
              href="https://www.linkedin.com/in/tejasnasa/"
              target="_blank"
              className="hover:text-(--foreground) transition-colors"
            >
              <LinkedinLogoIcon weight="fill" />
            </a>
            <a
              href="https://x.com/tejasnasa/"
              target="_blank"
              className="hover:text-(--foreground) transition-colors"
            >
              <XLogoIcon />
            </a>
          </div>
        </div>
      </footer>
    </main>
  );
}
