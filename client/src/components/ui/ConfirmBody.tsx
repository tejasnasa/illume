/**
 * Body layout shared by confirmation dialogs.
 * @module ConfirmBody
 */

/**
 * The confirmation dialog's body: a title, an explanation and a footer row.
 *
 * @param title The dialog's heading.
 * @param danger Colours the heading red.
 * @param children The explanation and any input.
 * @param footer The confirm button and any error.
 * @returns The dialog content.
 */
export default function ConfirmBody({
  title,
  danger = false,
  children,
  footer,
}: {
  title: string;
  danger?: boolean;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <div className="flex w-full flex-col gap-4">
      <h2 className={`m-0 font-pixel text-xl font-normal ${danger ? "text-red-400" : ""}`}>
        {title}
      </h2>
      <div className="flex flex-col gap-3 text-sm leading-relaxed text-(--muted-foreground)">
        {children}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 pt-2">{footer}</div>
    </div>
  );
}
