import { getRepositories } from "@/api/repository";
import DashboardRefresh from "@/components/DashboardRefresh";
import Navbar from "@/components/Navbar";
import RepoForm from "@/components/RepoForm";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import RepoCard from "@/components/ui/RepoCard";
import { DatabaseIcon, PlusIcon } from "@phosphor-icons/react/dist/ssr";
import { Suspense } from "react";

export default async function Dashboard() {
  const repositories = await getRepositories();

  return (
    <div className="min-h-screen">
      <Navbar />
      <DashboardRefresh repositories={repositories} />

      <main className="max-w-7xl mx-auto px-6 py-24">
        <header className="flex flex-col md:flex-row justify-between items-start md:items-end gap-6 mb-16">
          <div>
            <h1 className="text-8xl font-extrabold tracking-tight">
              Dashboard
            </h1>
            <p className="text-(--muted-foreground) text-lg">
              Manage and explore your indexed codebases.
            </p>
          </div>

          <Modal
            trigger={
              <Button size="lg">
                <PlusIcon weight="bold" size={20} />
                Add New Repository
              </Button>
            }
          >
            <div className="flex flex-col items-center">
              <h2 className="text-3xl font-bold mb-1 flex items-center gap-2">
                <DatabaseIcon className="text-(--primary)" />
                Index Repository
              </h2>
              <p className="text-sm text-(--muted-foreground) mb-4">
                Paste a GitHub URL to start the AI analysis pipeline.
              </p>
              <RepoForm />
            </div>
          </Modal>
        </header>

        <section className="relative">
          <div className="absolute -top-8 left-0 text-xs font-bold uppercase tracking-[0.2em] text-(--muted-foreground)/50">
            Your Indexed Libraries
          </div>

          <Suspense
            fallback={
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {repositories.map((repo) => (
                  <RepoCard key={repo.id} repo={repo} />
                ))}
              </div>
            }
          >
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {repositories.map((repo) => (
                <RepoCard key={repo.id} repo={repo} />
              ))}
            </div>
          </Suspense>

          {repositories.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 border-2 border-dashed border-(--border) rounded-3xl bg-(--secondary)/5">
              <DatabaseIcon
                size={48}
                className="text-(--muted-foreground)/20 mb-4"
              />
              <p className="text-(--muted-foreground)">
                No repositories found. Add your first one to get started!
              </p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
