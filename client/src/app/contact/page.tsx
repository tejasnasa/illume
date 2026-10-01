/**
 * Public contact page.
 * @module ContactPage
 */
import GetMyData from "@/api/auth";
import AppFooter from "@/components/AppFooter";
import ContactForm from "@/components/ContactForm";
import Navbar from "@/components/Navbar";
import { StarFourIcon } from "@phosphor-icons/react/dist/ssr";
import type { Metadata } from "next";
import Link from "next/link";

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

      {!user && (
        <nav className="fixed top-0 inset-x-0 z-50 backdrop-blur-xl border-b border-(--border)">
          <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
            <Link
              href={"/"}
              className="relative h-12 flex items-center justify-center m-2 gap-2"
            >
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="h-10 w-40 rounded-full bg-(--chart-1)/30 blur-xl" />
              </div>
              <StarFourIcon
                className="relative text-(--chart-1)"
                weight="fill"
                size={24}
              />
              <span className="text-xl font-semibold">Illume</span>
            </Link>

            <div className="flex items-center gap-1">
              {["Features", "How It Works"].map((item) => (
                <a
                  key={item}
                  href={`#${item.toLowerCase().replace(/\s+/g, "-")}`}
                  className="hidden sm:block px-4 py-2 text-sm text-(--muted-foreground) hover:text-(--foreground) rounded-lg hover:bg-(--secondary) transition-all duration-200"
                >
                  {item}
                </a>
              ))}
              <Link
                href="/contact"
                className="hidden sm:block px-4 py-2 text-sm text-(--muted-foreground) hover:text-(--foreground) rounded-lg hover:bg-(--secondary) transition-all duration-200"
              >
                Contact
              </Link>
              {/* <Link
              href="/login"
              className="ml-2 flex items-center gap-2 px-5 py-2 text-sm rounded-full border border-(--primary) text-(--muted-foreground) hover:text-(--foreground) hover:border-(--primary) transition-all duration-200"
            >
              <span className="hidden sm:inline">Login</span>
            </Link> */}
              <Link
                href="/login"
                className="ml-2 flex items-center gap-2 px-4 py-2 text-sm rounded-full border bg-(--primary) border-(--border)  hover:border-white transition-all duration-200"
              >
                <span className="sm:inline">Login</span>
              </Link>
            </div>
          </div>
        </nav>
      )}

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
