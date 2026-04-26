import RepoNavSkel from "@/components/ui/RepoNavSkel";
import {
  GithubLogoIcon,
  HouseIcon,
  LinkIcon,
  MagnifyingGlassIcon,
} from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

export default function NotFound() {
  return (
    <>
      <RepoNavSkel />
      <main className="p-4 h-[calc(100vh-64px)] flex gap-4 max-w-7xl mx-auto">
        <section className="w-1/2 flex flex-col gap-4 h-full">
          <div className="grid grid-cols-2 gap-4 h-30 shrink-0">
            <div className="group relative glass-card rounded-sm overflow-hidden border border-(--destructive)/30">
              <div className="absolute inset-0 bg-linear-to-br from-(--destructive)/10 to-transparent" />
              <div className="absolute top-4 right-4 text-(--destructive)/50">
                <LinkIcon size={20} />
              </div>
              <div className="p-4 flex flex-col justify-between h-full">
                <span className="text-xs font-semibold uppercase tracking-wider text-(--muted-foreground)">
                  Repository
                </span>
                <h2 className="text-2xl font-bold flex items-center gap-3 text-(--muted-foreground) truncate">
                  <GithubLogoIcon
                    size={28}
                    weight="fill"
                    className="shrink-0"
                  />
                  <span className="truncate">Not Found</span>
                </h2>
              </div>
            </div>

            <div className="glass-card rounded-sm p-4 flex flex-col justify-between border border-(--destructive)/30">
              <span className="text-xs font-semibold uppercase tracking-wider text-(--muted-foreground)">
                Status
              </span>
              <div className="flex items-end justify-between">
                <div className="flex items-center gap-2 font-bold text-xl uppercase text-(--destructive)">
                  <MagnifyingGlassIcon size={24} />
                  404
                </div>
                <div className="text-right text-xs text-(--muted-foreground) opacity-60">
                  <p>Repository</p>
                  <p>does not exist</p>
                </div>
              </div>
            </div>
          </div>

          <div className="glass-card rounded-sm p-6 flex-1 min-h-0 flex flex-col border border-(--border) bg-(--secondary)/10 items-center justify-center gap-6">
            <div className="flex flex-col items-center gap-3 text-center">
              <span className="text-6xl font-black text-(--destructive)/20 tracking-tighter">
                404
              </span>
              <h2 className="text-xl font-bold text-(--foreground)">
                Repository Not Found
              </h2>
              <p className="text-sm text-(--muted-foreground) max-w-xs leading-relaxed">
                The repository you're looking for doesn't exist or you may not
                have access to it.
              </p>
            </div>

            <Link
              href="/dashboard"
              className="flex items-center gap-2 px-4 py-2 bg-(--primary)/10 hover:bg-(--primary)/20 border border-(--primary)/30 text-(--primary) text-sm font-semibold rounded-sm transition-colors"
            >
              <HouseIcon size={16} />
              Back to Dashboard
            </Link>
          </div>

          <div className="glass-card rounded-sm p-6 shrink-0 h-40 flex flex-col border border-(--border) bg-(--secondary)/10 justify-center">
            <p className="text-xs font-semibold uppercase tracking-wider text-(--muted-foreground) mb-3">
              Possible Reasons
            </p>
            <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-xs text-(--muted-foreground)">
              <span className="opacity-70">— Invalid repository ID</span>
              <span className="opacity-70">— Access was revoked</span>
              <span className="opacity-70">— Repository was deleted</span>
              <span className="opacity-70">— Wrong URL</span>
            </div>
          </div>
        </section>

        <section className="w-1/2 h-full flex flex-col glass-card rounded-sm overflow-hidden border border-(--destructive)/20">
          <div className="w-full h-full flex flex-col">
            <div className="flex items-center justify-between p-4 shrink-0 border-b bg-(--background)/50">
              <h2 className="text-xl font-bold flex items-center gap-2 text-(--muted-foreground)">
                <span className="w-2.5 h-2.5 rounded-full bg-(--destructive)/50 shadow-[0_0_8px_var(--destructive)]" />
                Chat with Codebase
              </h2>
            </div>

            <div className="flex-1 flex flex-col items-center justify-center gap-3 p-6 text-center">
              <MagnifyingGlassIcon
                size={40}
                className="text-(--muted-foreground)/30"
              />
              <p className="text-sm text-(--muted-foreground) italic">
                No repository loaded.
              </p>
            </div>
          </div>
        </section>
      </main>
    </>
  );
}
