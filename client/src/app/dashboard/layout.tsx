/**
 * Layout for the dashboard route.
 * @module DashboardLayout
 */
import AppFooter from "@/components/AppFooter";

/**
 * Wraps the dashboard with the shared footer.
 *
 * A full-height flex column so the footer rests at the bottom of the viewport while the
 * dashboard's content is shorter than the screen -- an account with no repositories yet
 * -- and below the content otherwise. `dvh` rather than `vh` because on mobile browsers
 * `vh` is measured before the URL bar collapses, which would push the footer off-screen.
 *
 * @param children - The dashboard route content.
 * @returns The dashboard shell.
 */
export default function DashboardLayout({
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
