/**
 * Global 404 page.
 * @module NotFoundPage
 */
import SiteNavbar from "@/components/SiteNavbar";
import StatusScreen, { STATUS_PRIMARY } from "@/components/ui/StatusScreen";
import Link from "next/link";

/**
 * Renders the not-found state with a dashboard recovery link.
 *
 * Most visitors land here from a stale repository link, so the explanation
 * leads with the reasons a repository goes missing.
 *
 * @returns The 404 page.
 */
export default function NotFound() {
  return (
    <>
      <SiteNavbar />
      <StatusScreen
        command="illume open"
        code="404"
        title="Page not found"
        actions={
          <Link href="/dashboard" className={STATUS_PRIMARY}>
            Back to dashboard <span aria-hidden="true">→</span>
          </Link>
        }
      >
        <p className="m-0">
          Nothing lives at this address. If you followed a link to a
          repository, it may have been deleted, re-added under a new number, or
          belong to another account.
        </p>
      </StatusScreen>
    </>
  );
}
