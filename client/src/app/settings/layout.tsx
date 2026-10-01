/**
 * Layout for the settings route.
 * @module SettingsLayout
 */
import AppFooter from "@/components/AppFooter";

/**
 * Wraps the settings page with the shared footer.
 *
 * Mirrors the dashboard shell so the footer sits in the same place on every signed-in
 * page: pinned to the bottom of the viewport on a short page, below the content on a
 * tall one.
 *
 * @param children - The settings route content.
 * @returns The settings shell.
 */
export default function SettingsLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div className="min-h-dvh flex flex-col">
      {children}
      <AppFooter />
    </div>
  );
}
