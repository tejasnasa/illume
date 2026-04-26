"use client";

import { GearFineIcon, StarFourIcon } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";
import { usePathname } from "next/navigation";
import RepoSettings from "./RepoSettings";
import Modal from "./ui/Modal";

export default function RepoNavbar({
  name,
  num_id,
  id,
  status,
}: {
  name: string;
  num_id: number;
  id: string;
  status: string;
}) {
  const path = usePathname();
  return (
    <header className="flex backdrop-blur-xs items-center justify-between sticky top-0 z-10 print:hidden">
      <section className="flex items-center">
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
        <h1 className="text-xl font-medium mx-2">{name}</h1>
        <div className="bg-green-500 text-(--background) rounded-full px-3 py-1 text-xs font-medium">
          {status}
        </div>
      </section>

      {status === "ready" && (
        <section className="flex items-center">
          <Link
            href={`/repo/${num_id}`}
            className={`m-2 mx-4  ${path === `/repo/${num_id}` ? "text-(--foreground) font-semibold" : "text-(--muted-foreground)"}`}
          >
            Home
          </Link>
          {/* <Link
          href={`/repo/${num_id}/onboarding-guide`}
          className={`m-2 mx-4  ${path === `/repo/${num_id}/onboarding-guide` ? "text-(--foreground) font-semibold" : "text-(--muted-foreground)"}`}
        >
          Onboarding Guide
        </Link> */}
          <Link
            href={`/repo/${num_id}/glossary`}
            className={`m-2 mx-4  ${path === `/repo/${num_id}/glossary` ? "text-(--foreground) font-semibold" : "text-(--muted-foreground)"}`}
          >
            Glossary
          </Link>
          <Link
            href={`/repo/${num_id}/explorer`}
            className={`m-2 mx-4  ${path === `/repo/${num_id}/explorer` ? "text-(--foreground) font-semibold" : "text-(--muted-foreground)"}`}
          >
            Explorer
          </Link>
          <Link
            href={`/repo/${num_id}/graph`}
            className={`m-2 mx-4  ${path === `/repo/${num_id}/graph` ? "text-(--foreground) font-semibold" : "text-(--muted-foreground)"}`}
          >
            Graph
          </Link>
          <Modal
            trigger={
              <GearFineIcon
                size={24}
                className="m-2 mx-4 mr-6 text-(--muted-foreground) hover:cursor-pointer"
              />
            }
          >
            <RepoSettings repo_id={id} />
          </Modal>
        </section>
      )}

      {status !== "ready" && (
        <section className="flex items-center">
          <div className="m-2 mx-4 font-semibold">Home</div>
          <div className="m-2 mx-4 text-(--muted-foreground) animate-pulse">
            Glossary
          </div>
          <div className="m-2 mx-4 text-(--muted-foreground) animate-pulse">
            Explorer
          </div>
          <div className="m-2 mx-4 text-(--muted-foreground) animate-pulse">
            Graph
          </div>
          <Modal
            trigger={
              <GearFineIcon
                size={24}
                className="m-2 mx-4 mr-6 text-(--muted-foreground) hover:cursor-pointer"
              />
            }
          >
            <RepoSettings repo_id={id} />
          </Modal>
        </section>
      )}
    </header>
  );
}
