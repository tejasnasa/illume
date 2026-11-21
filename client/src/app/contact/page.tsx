/**
 * Public contact page.
 * @module ContactPage
 */
import GetMyData from "@/api/auth";
import AppFooter from "@/components/AppFooter";
import ContactForm from "@/components/ContactForm";
import Navbar from "@/components/Navbar";
import SiteNavbar from "@/components/SiteNavbar";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Contact - Illume",
  description:
    "Report a bug, request a feature, or ask a question about Illume. No account needed.",
};

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
    <div className="min-h-dvh flex flex-col">
      {user && <Navbar userData={user} />}

      {!user && <SiteNavbar />}

      <main className={`flex-1 flex flex-col items-center px-6 ${user ? "py-12 sm:py-16" : "pb-16 pt-24 sm:pb-24 sm:pt-32" }`}>
        <div className="w-full max-w-2xl mb-10">
          <h1 className="text-5xl font-extrabold tracking-tight mb-2">
            Get In Touch
          </h1>
          <p className="text-(--muted-foreground) text-lg">
            Found a bug, want a feature, or just have a question? Send it over
            and we&apos;ll reply by email.
          </p>
        </div>

        <ContactForm defaultName={user?.name} defaultEmail={user?.email} />
      </main>

      <AppFooter />
    </div>
  );
}
