/**
 * User dashboard listing indexed repositories.
 * @module DashboardPage
 */
import GetMyData from "@/api/auth";
import { getRepositories } from "@/api/repository";
import AddRepoDialog from "@/components/AddRepoDialog";
import DashboardRefresh from "@/components/DashboardRefresh";
import FreeTierBanner from "@/components/FreeTierBanner";
import Navbar from "@/components/Navbar";
import RepoCollection from "@/components/RepoCollection";
import User from "@/types/user";
import { statusView } from "@/utils/repoStatus";

/**
 * The cost line shown on the picker's version step for keyless users.
 *
 * @param user The signed-in user.
 * @returns The note, or undefined when the user has their own key.
 */
function ingestNote(user: User): string | undefined {
  if (user.has_ai_key) return undefined;
  return `Uses 1 of your ${user.free_ingestions_limit} free repositories`;
}

/**
 * Server-rendered dashboard: header, free-tier strip and the repository
 * collection.
 *
 * @returns Dashboard layout with navbar, refresh handler, and repositories.
 */
export default async function Dashboard() {
  const [repositories, myData] = await Promise.all([
    getRepositories(),
    GetMyData(),
  ]);

  const ingesting = repositories.filter(
    (r) => statusView(r.status).kind === "ingesting",
  ).length;
  const count = `${repositories.length} ${repositories.length === 1 ? "repository" : "repositories"}`;

  return (
    <div className="flex min-h-dvh flex-col">
      <Navbar userData={myData} page="Dashboard" />
      <DashboardRefresh repositories={repositories} />

      <main className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-4 pt-14 pb-24 sm:px-6">
        <header className="flex flex-wrap items-end justify-between gap-6">
          <div className="flex flex-col gap-3">
            <p
              aria-hidden="true"
              className="m-0 font-pixel text-[13px] tracking-[0.08em] text-(--subtle-foreground)"
            >
              <span className="text-(--accent)">&gt;</span> illume ls
              <span className="caret">_</span>
            </p>
            <h1 className="m-0 text-4xl font-medium tracking-tight sm:text-5xl">
              Your <span className="font-pixel text-(--accent)">repositories</span>
            </h1>
            <p className="m-0 font-pixel text-xs tracking-[0.08em] text-(--muted-foreground) uppercase">
              {count}
              {ingesting > 0 && (
                <>
                  {" "}
                  · <span className="text-(--accent)">{ingesting} ingesting</span>
                </>
              )}
            </p>
          </div>
          <AddRepoDialog
            note={ingestNote(myData)}
            added={repositories.map((repo) => repo.github_url)}
          />
        </header>

        <FreeTierBanner user={myData} />

        <RepoCollection repositories={repositories} />
      </main>
    </div>
  );
}
