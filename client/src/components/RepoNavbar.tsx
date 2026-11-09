/**
 * Repository header with section links and settings access.
 * @module RepoNavbar
 */
"use client";

import {
  CircleDashedIcon,
  GearFineIcon,
  StarFourIcon,
} from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";
import { usePathname } from "next/navigation";
import Repository from "@/types/repository";
import RepoSettings from "./RepoSettings";
import Modal from "./ui/Modal";

/**
 * Shows repo identity, status, and navigation to its sections.
 *
 * @param name - Display name of the repository.
 * @param num_id - Numeric ID used in section routes.
 * @param id - UUID used for settings actions.
 * @param status - Ingestion status; non-ready repos show placeholder links.
 * @param github_url - Repository URL forwarded to settings.
 * @param sync_status - Background-sync status; an active value shows a small spinner next to the badge.
 * @returns Sticky header with active-link highlighting and settings modal.
 */
export default function RepoNavbar({ repo }: { repo: Repository }) {
  const path = usePathname();
  const { name, status, repo_number, sync_status } = repo;
  const isSyncing =
    sync_status === "queued" ||
    sync_status === "checking" ||
    sync_status === "updating";

  return (
    <header className="flex backdrop-blur-xs items-center justify-between sticky top-0 z-10 print:hidden">
      <section className="flex min-w-0 shrink-0 items-center">
        <Link
          href={"/dashboard"}
          className="relative h-12 w-12 flex items-center justify-center m-2"
        >
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="h-10 w-10 rounded-full bg-(--chart-1)/30 blur-xl" />
          </div>
          <StarFourIcon
            className="relative text-(--chart-1)"
            weight="fill"
            size={24}
          />
        </Link>
        <h1 className="mx-2 hidden truncate text-xl font-medium sm:block">{name}</h1>
        <div className="hidden bg-green-500 text-(--background) rounded-full px-3 py-1 text-xs font-medium items-center gap-1.5 sm:inline-flex">
          {isSyncing && (
            <CircleDashedIcon
              size={11}
              className="animate-spin"
              weight="bold"
            />
          )}
          {status}
        </div>
      </section>

      {status === "ready" && (
        <section className="flex min-w-0 items-center overflow-x-auto [scrollbar-width:none]">
          <Link
            href={`/repo/${repo_number}`}
            className={`m-2 mx-2 shrink-0 text-sm md:mx-4 md:text-base ${path === `/repo/${repo_number}` ? "text-(--foreground) font-semibold" : "text-(--muted-foreground)"}`}
          >
            Home
          </Link>
          <Link
            href={`/repo/${repo_number}/chat`}
            className={`m-2 mx-2 shrink-0 text-sm md:mx-4 md:text-base ${path === `/repo/${repo_number}/chat` ? "text-(--foreground) font-semibold" : "text-(--muted-foreground)"}`}
          >
            Chat
          </Link>
          {/* <Link
          href={`/repo/${repo_number}/onboarding-guide`}
          className={`m-2 mx-2 shrink-0 text-sm md:mx-4 md:text-base ${path === `/repo/${repo_number}/onboarding-guide` ? "text-(--foreground) font-semibold" : "text-(--muted-foreground)"}`}
        >
          Onboarding Guide
        </Link> */}
          <Link
            href={`/repo/${repo_number}/glossary`}
            className={`m-2 mx-2 shrink-0 text-sm md:mx-4 md:text-base ${path === `/repo/${repo_number}/glossary` ? "text-(--foreground) font-semibold" : "text-(--muted-foreground)"}`}
          >
            Glossary
          </Link>
          <Link
            href={`/repo/${repo_number}/explorer`}
            className={`m-2 mx-2 shrink-0 text-sm md:mx-4 md:text-base ${path === `/repo/${repo_number}/explorer` ? "text-(--foreground) font-semibold" : "text-(--muted-foreground)"}`}
          >
            Explorer
          </Link>
          <Link
            href={`/repo/${repo_number}/graph`}
            className={`m-2 mx-2 shrink-0 text-sm md:mx-4 md:text-base ${path === `/repo/${repo_number}/graph` ? "text-(--foreground) font-semibold" : "text-(--muted-foreground)"}`}
          >
            Graph
          </Link>
          <Modal
            label="Repository settings"
            trigger={
              <GearFineIcon
                size={24}
                className="m-2 mx-2 mr-4 shrink-0 text-(--muted-foreground) hover:cursor-pointer md:mx-4 md:mr-6"
              />
            }
          >
            <RepoSettings repo={repo} />
          </Modal>
        </section>
      )}

      {status !== "ready" && (
        <section className="flex min-w-0 items-center overflow-x-auto [scrollbar-width:none]">
          <div className="m-2 mx-2 shrink-0 text-sm font-semibold md:mx-4 md:text-base">Home</div>
          <div className="m-2 mx-2 shrink-0 text-sm text-(--muted-foreground) animate-pulse md:mx-4 md:text-base">
            Chat
          </div>
          <div className="m-2 mx-2 shrink-0 text-sm text-(--muted-foreground) animate-pulse md:mx-4 md:text-base">
            Glossary
          </div>
          <div className="m-2 mx-2 shrink-0 text-sm text-(--muted-foreground) animate-pulse md:mx-4 md:text-base">
            Explorer
          </div>
          <div className="m-2 mx-2 shrink-0 text-sm text-(--muted-foreground) animate-pulse md:mx-4 md:text-base">
            Graph
          </div>
          <Modal
            label="Repository settings"
            trigger={
              <GearFineIcon
                size={24}
                className="m-2 mx-2 mr-4 shrink-0 text-(--muted-foreground) hover:cursor-pointer md:mx-4 md:mr-6"
              />
            }
          >
            <RepoSettings repo={repo} />
          </Modal>
        </section>
      )}
    </header>
  );
}
