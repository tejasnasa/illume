import Navbar from "@/components/Navbar";
import Skeleton from "@/components/ui/Skeleton";
import {
  ArrowRightIcon,
  GithubLogoIcon,
  SparkleIcon,
} from "@phosphor-icons/react/dist/ssr";

export default function LoadingDashboard() {
  return (
    <div className="min-h-screen text-(--muted-foreground)">
      <Navbar />

      <main className="max-w-7xl mx-auto px-6 py-24">
        <header className="flex flex-col md:flex-row justify-between items-start md:items-end gap-6 mb-16">
          <div>
            <h1 className="text-8xl font-extrabold tracking-tight animate-pulse text-(--muted-foreground)/70">
              Dashboard
            </h1>
            <p className="text-lg animate-pulse text-(--muted-foreground)/70">
              Manage and explore your indexed codebases.
            </p>
          </div>

          <Skeleton className="h-12 w-56 rounded-sm" />
        </header>

        <section className="relative">
          <div className="absolute -top-8 left-0 text-xs font-bold uppercase tracking-[0.2em] text-(--muted-foreground)/50  animate-pulse">
            Your Indexed Libraries
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {/* card */}
            <div className="group relative glass-card rounded-sm p-6 block hover:border-(--primary)/50 transition-all duration-300 hover:shadow-xl hover:shadow-(--primary)/5">
              <div className="absolute top-4 right-4 flex items-center gap-1 z-10">
                <div
                  className="p-2 rounded-sm text-(--muted-foreground) hover:text-(--foreground) hover:bg-(--secondary) transition-colors animate-pulse"
                  title="Open GitHub"
                >
                  <GithubLogoIcon size={20} />
                </div>
                <div className="p-2 text-(--muted-foreground) group-hover:translate-x-1 transition-all animate-pulse">
                  <ArrowRightIcon size={20} weight="bold" />
                </div>
              </div>

              <div className="flex items-start gap-4 mb-6 animate-pulse">
                <div className="p-3 rounded-xl bg-(--secondary)  group-hover:bg-(--primary)/10 transition-colors">
                  <SparkleIcon size={28} weight="fill" />
                </div>
                <div className="min-w-0">
                  <Skeleton className="h-5 w-32 rounded-sm mb-2 pr-12 pl-6" />
                  <div className="flex items-center gap-2 mt-1">
                    <Skeleton className="h-2.5 w-20 rounded-full" />
                    <Skeleton className="h-2.5 w-20 rounded-full" />
                  </div>
                </div>
              </div>

              <div className="h-25 flex items-center justify-center border-2 border-dashed border-(--border) rounded-xl mb-4 bg-(--secondary)/5">
                <Skeleton className="h-3 w-20 rounded-full" />
              </div>

              <div className="flex items-center gap-4 w-full">
                <div className="flex flex-col w-full">
                  <div className="flex gap-1 mt-1 overflow-x-hidden w-full">
                    <Skeleton className="h-2.25 w-20 rounded-full" />
                  </div>
                </div>
              </div>
            </div>
            {/* card */}
            <div className="group relative glass-card rounded-sm p-6 block hover:border-(--primary)/50 transition-all duration-300 hover:shadow-xl hover:shadow-(--primary)/5">
              <div className="absolute top-4 right-4 flex items-center gap-1 z-10">
                <div
                  className="p-2 rounded-sm text-(--muted-foreground) hover:text-(--foreground) hover:bg-(--secondary) transition-colors animate-pulse"
                  title="Open GitHub"
                >
                  <GithubLogoIcon size={20} />
                </div>
                <div className="p-2 text-(--muted-foreground) group-hover:translate-x-1 transition-all animate-pulse">
                  <ArrowRightIcon size={20} weight="bold" />
                </div>
              </div>

              <div className="flex items-start gap-4 mb-6 animate-pulse">
                <div className="p-3 rounded-xl bg-(--secondary)  group-hover:bg-(--primary)/10 transition-colors">
                  <SparkleIcon size={28} weight="fill" />
                </div>
                <div className="min-w-0">
                  <Skeleton className="h-5 w-32 rounded-sm mb-2 pr-12 pl-6" />
                  <div className="flex items-center gap-2 mt-1">
                    <Skeleton className="h-2.5 w-20 rounded-full" />
                    <Skeleton className="h-2.5 w-20 rounded-full" />
                  </div>
                </div>
              </div>

              <div className="h-25 flex items-center justify-center border-2 border-dashed border-(--border) rounded-xl mb-4 bg-(--secondary)/5">
                <Skeleton className="h-3 w-20 rounded-full" />
              </div>

              <div className="flex items-center gap-4 w-full">
                <div className="flex flex-col w-full">
                  <div className="flex gap-1 mt-1 overflow-x-hidden w-full">
                    <Skeleton className="h-2.25 w-20 rounded-full" />
                  </div>
                </div>
              </div>
            </div>
            {/* card */}
            <div className="group relative glass-card rounded-sm p-6 block hover:border-(--primary)/50 transition-all duration-300 hover:shadow-xl hover:shadow-(--primary)/5">
              <div className="absolute top-4 right-4 flex items-center gap-1 z-10">
                <div
                  className="p-2 rounded-sm text-(--muted-foreground) hover:text-(--foreground) hover:bg-(--secondary) transition-colors animate-pulse"
                  title="Open GitHub"
                >
                  <GithubLogoIcon size={20} />
                </div>
                <div className="p-2 text-(--muted-foreground) group-hover:translate-x-1 transition-all animate-pulse">
                  <ArrowRightIcon size={20} weight="bold" />
                </div>
              </div>

              <div className="flex items-start gap-4 mb-6 animate-pulse">
                <div className="p-3 rounded-xl bg-(--secondary)  group-hover:bg-(--primary)/10 transition-colors">
                  <SparkleIcon size={28} weight="fill" />
                </div>
                <div className="min-w-0">
                  <Skeleton className="h-5 w-32 rounded-sm mb-2 pr-12 pl-6" />
                  <div className="flex items-center gap-2 mt-1">
                    <Skeleton className="h-2.5 w-20 rounded-full" />
                    <Skeleton className="h-2.5 w-20 rounded-full" />
                  </div>
                </div>
              </div>

              <div className="h-25 flex items-center justify-center border-2 border-dashed border-(--border) rounded-xl mb-4 bg-(--secondary)/5">
                <Skeleton className="h-3 w-20 rounded-full" />
              </div>

              <div className="flex items-center gap-4 w-full">
                <div className="flex flex-col w-full">
                  <div className="flex gap-1 mt-1 overflow-x-hidden w-full">
                    <Skeleton className="h-2.25 w-20 rounded-full" />
                  </div>
                </div>
              </div>
            </div>
            {/* card */}
            <div className="group relative glass-card rounded-sm p-6 block hover:border-(--primary)/50 transition-all duration-300 hover:shadow-xl hover:shadow-(--primary)/5">
              <div className="absolute top-4 right-4 flex items-center gap-1 z-10">
                <div
                  className="p-2 rounded-sm text-(--muted-foreground) hover:text-(--foreground) hover:bg-(--secondary) transition-colors animate-pulse"
                  title="Open GitHub"
                >
                  <GithubLogoIcon size={20} />
                </div>
                <div className="p-2 text-(--muted-foreground) group-hover:translate-x-1 transition-all animate-pulse">
                  <ArrowRightIcon size={20} weight="bold" />
                </div>
              </div>

              <div className="flex items-start gap-4 mb-6 animate-pulse">
                <div className="p-3 rounded-xl bg-(--secondary)  group-hover:bg-(--primary)/10 transition-colors">
                  <SparkleIcon size={28} weight="fill" />
                </div>
                <div className="min-w-0">
                  <Skeleton className="h-5 w-32 rounded-sm mb-2 pr-12 pl-6" />
                  <div className="flex items-center gap-2 mt-1">
                    <Skeleton className="h-2.5 w-20 rounded-full" />
                    <Skeleton className="h-2.5 w-20 rounded-full" />
                  </div>
                </div>
              </div>

              <div className="h-25 flex items-center justify-center border-2 border-dashed border-(--border) rounded-xl mb-4 bg-(--secondary)/5">
                <Skeleton className="h-3 w-20 rounded-full" />
              </div>

              <div className="flex items-center gap-4 w-full">
                <div className="flex flex-col w-full">
                  <div className="flex gap-1 mt-1 overflow-x-hidden w-full">
                    <Skeleton className="h-2.25 w-20 rounded-full" />
                  </div>
                </div>
              </div>
            </div>
            {/* card */}
            <div className="group relative glass-card rounded-sm p-6 block hover:border-(--primary)/50 transition-all duration-300 hover:shadow-xl hover:shadow-(--primary)/5">
              <div className="absolute top-4 right-4 flex items-center gap-1 z-10">
                <div
                  className="p-2 rounded-sm text-(--muted-foreground) hover:text-(--foreground) hover:bg-(--secondary) transition-colors animate-pulse"
                  title="Open GitHub"
                >
                  <GithubLogoIcon size={20} />
                </div>
                <div className="p-2 text-(--muted-foreground) group-hover:translate-x-1 transition-all animate-pulse">
                  <ArrowRightIcon size={20} weight="bold" />
                </div>
              </div>

              <div className="flex items-start gap-4 mb-6 animate-pulse">
                <div className="p-3 rounded-xl bg-(--secondary)  group-hover:bg-(--primary)/10 transition-colors">
                  <SparkleIcon size={28} weight="fill" />
                </div>
                <div className="min-w-0">
                  <Skeleton className="h-5 w-32 rounded-sm mb-2 pr-12 pl-6" />
                  <div className="flex items-center gap-2 mt-1">
                    <Skeleton className="h-2.5 w-20 rounded-full" />
                    <Skeleton className="h-2.5 w-20 rounded-full" />
                  </div>
                </div>
              </div>

              <div className="h-25 flex items-center justify-center border-2 border-dashed border-(--border) rounded-xl mb-4 bg-(--secondary)/5">
                <Skeleton className="h-3 w-20 rounded-full" />
              </div>

              <div className="flex items-center gap-4 w-full">
                <div className="flex flex-col w-full">
                  <div className="flex gap-1 mt-1 overflow-x-hidden w-full">
                    <Skeleton className="h-2.25 w-20 rounded-full" />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
