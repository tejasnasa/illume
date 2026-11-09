/**
 * The panel every card on the repository overview is built from.
 * @module DashboardCard
 */
import Link from "next/link";
import type { ElementType, ReactNode } from "react";

/**
 * A glass panel with an optional icon-led title and a slot on the right of
 * the title for a link or control.
 *
 * @param icon - Icon shown before the title.
 * @param title - The panel's heading; leave it out for a panel that lays out
 *   its own header.
 * @param action - Shown at the right end of the heading row.
 * @param href - Makes the whole panel a link; external URLs open in a new tab.
 * @param className - Extra classes, typically for sizing in the page layout.
 * @param children - The panel's body.
 * @returns The panel.
 */
export default function DashboardCard({
  icon: Icon,
  title,
  action,
  href,
  className = "",
  children,
}: {
  icon?: ElementType;
  title?: string;
  action?: ReactNode;
  href?: string;
  className?: string;
  children: ReactNode;
}) {
  const classes = `glass-card rounded-sm p-4 flex flex-col animate-fade-in ${className}`;
  const body = (
    <>
      {title && (
        <header className="mb-3 flex shrink-0 items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-lg font-bold text-(--foreground)">
            {Icon && <Icon size={20} className="text-(--primary)" />}
            {title}
          </h2>
          {action}
        </header>
      )}
      {children}
    </>
  );

  if (href) {
    const external = /^https?:\/\//.test(href);
    return (
      <Link
        href={href}
        target={external ? "_blank" : undefined}
        rel={external ? "noopener noreferrer" : undefined}
        className={`group relative overflow-hidden transition-colors hover:border-(--primary)/50 ${classes}`}
      >
        {body}
      </Link>
    );
  }
  return <section className={classes}>{body}</section>;
}
