/**
 * Public contact page.
 * @module ContactPage
 */
import GetMyData from "@/api/auth";
import AppFooter from "@/components/AppFooter";
import ContactForm from "@/components/ContactForm";
import Navbar from "@/components/Navbar";
import PixelGraph from "@/components/PixelGraph";
import SiteNavbar from "@/components/SiteNavbar";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Contact - Illume",
  description:
    "Report a bug, request a feature, or ask a question about Illume. No account needed.",
};

/** Places to reach the project without the form. */
const DIRECT_LINKS = [
  {
    title: "Open an issue",
    caption: "github.com/tejasnasa/illume",
    href: "https://github.com/tejasnasa/illume/issues",
  },
  {
    title: "Tejas on GitHub",
    caption: "@tejasnasa",
    href: "https://github.com/tejasnasa",
  },
  {
    title: "Personal site",
    caption: "tejasnasa.me",
    href: "https://tejasnasa.me",
  },
] as const;

/**
 * Renders the contact page, prefilling identity for a signed-in visitor.
 *
 * A server component because the prefill has to come from the session: the cookie is
 * httpOnly, so only the server can read it, and reading it here keeps the interactive
 * part of the page in the leaf form component.
 *
 * @returns The contact page.
 */
export default async function Contact() {
  let user = null;
  try {
    user = await GetMyData();
  } catch {
    // Anonymous, or the API is unreachable. Both render the same form: a contact page
    // that could not be used while the API was down would be useless for reporting
    // exactly that.
  }

  return (
    <div className="flex min-h-dvh flex-col">
      {user ? <Navbar userData={user} /> : <SiteNavbar />}

      {/* The gutter lines both columns up with the navbar's content edges. */}
      <main
        className={`grid flex-1 grid-cols-1 [--gutter:max(1.5rem,calc((100vw-80rem)/2+1.5rem))] lg:grid-cols-2 ${user ? "" : "pt-16"}`}
      >
        <section className="relative flex flex-col justify-between gap-10 overflow-hidden border-white/10 bg-[radial-gradient(ellipse_at_30%_40%,#0092b81f,transparent_65%)] px-4 py-12 sm:px-6 sm:py-14 lg:min-h-140 lg:border-r lg:pr-12 lg:pl-(--gutter)">
          <PixelGraph source="hero" focusLabel={false} className="opacity-55" />
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,#09090bf2_0%,#09090b99_45%,#09090bf2_100%)]"
          />
          <div className="relative flex flex-col gap-4">
            <p
              aria-hidden="true"
              className="m-0 font-pixel text-[13px] tracking-[0.12em] text-(--muted-foreground)"
            >
              &gt; illume contact<span className="caret text-(--accent)">_</span>
            </p>
            <h1 className="m-0 font-pixel text-[clamp(2.4rem,5vw,4.4rem)] leading-none font-normal tracking-[-0.02em]">
              Get in <span className="gradient-text pb-[0.06em]">touch</span>
            </h1>
            <p className="m-0 max-w-110 text-[17px] leading-relaxed text-zinc-400">
              Found a bug, want a feature, or just have a question? Send it over
              and you will get a reply by email. No account needed.
            </p>
          </div>

          <div className="relative flex max-w-110 flex-col gap-2.5">
            <span className="font-pixel text-[11px] tracking-[0.12em] text-zinc-500 uppercase">
              Or reach out directly
            </span>
            {DIRECT_LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-between gap-3 rounded-sm border border-white/10 bg-(--card)/80 px-4 py-3.5 text-(--foreground) transition-colors duration-200 ease-[steps(2)] hover:border-(--accent)"
              >
                <span className="flex flex-col gap-0.5">
                  <span className="text-[15px]">{link.title}</span>
                  <span className="font-pixel text-[11px] tracking-[0.06em] text-zinc-500 uppercase">
                    {link.caption}
                  </span>
                </span>
                <span aria-hidden="true" className="font-pixel text-zinc-500">
                  ↗
                </span>
              </a>
            ))}
          </div>
        </section>

        <section className="flex items-center justify-center px-4 py-12 sm:px-6 sm:py-14 lg:pr-(--gutter) lg:pl-12">
          <ContactForm defaultName={user?.name} defaultEmail={user?.email} />
        </section>
      </main>

      <AppFooter />
    </div>
  );
}
