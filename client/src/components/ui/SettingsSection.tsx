/**
 * The two-column block every settings page is built from: a title and
 * explanation on the left, the controls on the right.
 * @module SettingsSection
 */
import type { ReactNode } from "react";

/**
 * Renders one settings section.
 *
 * @param id Used to label the section by its heading.
 * @param title The section's heading.
 * @param description Explanation under the heading.
 * @param tone `danger` colours the heading for destructive sections.
 * @param children The controls.
 * @returns The section.
 */
export default function SettingsSection({
  id,
  title,
  description,
  tone = "default",
  children,
}: {
  id: string;
  title: string;
  description?: ReactNode;
  tone?: "default" | "danger";
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={id}
      className="grid grid-cols-1 gap-4 border-t border-(--border) py-8 md:grid-cols-[240px_minmax(0,1fr)] md:gap-8"
    >
      <div className="flex flex-col gap-2">
        <h2
          id={id}
          className={`m-0 font-pixel text-lg font-normal ${tone === "danger" ? "text-red-400" : ""}`}
        >
          {title}
        </h2>
        {description && (
          <div className="text-sm leading-relaxed text-(--muted-foreground)">{description}</div>
        )}
      </div>
      <div className="flex min-w-0 flex-col gap-3">{children}</div>
    </section>
  );
}

/**
 * A row card: a label and explanation on the left, an action on the right.
 *
 * @param title What the row does.
 * @param description A line or two of detail.
 * @param action The control.
 * @param tone `danger` tints the card red.
 * @param children Anything shown under the row, such as an error.
 * @returns The card.
 */
export function SettingsRow({
  title,
  description,
  action,
  tone = "default",
  children,
}: {
  title: string;
  description?: ReactNode;
  action: ReactNode;
  tone?: "default" | "danger";
  children?: ReactNode;
}) {
  return (
    <div
      className={`flex flex-col gap-3 rounded-md border p-5 ${tone === "danger" ? "border-red-500/25 bg-red-500/4" : "border-(--border) bg-(--card)"}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-4">
        <span className="flex max-w-120 flex-col gap-1">
          <span className="text-[15px]">{title}</span>
          {description && (
            <span className="text-[13px] leading-normal text-(--muted-foreground)">
              {description}
            </span>
          )}
        </span>
        {action}
      </div>
      {children}
    </div>
  );
}
