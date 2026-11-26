/**
 * Root application layout with fonts and metadata.
 * @module RootLayout
 */
import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistPixelSquare } from "geist/font/pixel/square";
import Starfield from "@/components/Starfield";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://illume.tejasnasa.me"),
  title: "Illume - AI Powered Codebase Onboarding Platform",
  description:
    "Transform dense repositories into interactive onboarding guides. Architecture briefs, reading orders, glossaries, and ownership maps — all automated.",
  keywords: [
    "codebase onboarding",
    "code analysis",
    "dependency graph",
    "AI code tool",
    "RAG",
    "developer tool",
  ],
  applicationName: "Illume",
  openGraph: {
    type: "website",
    url: "https://illume.tejasnasa.me",
    title: "Illume - AI Powered Codebase Onboarding Platform",
    description:
      "Transform dense repositories into interactive onboarding guides. Architecture briefs, reading orders, glossaries, and ownership maps — all automated.",
    siteName: "Illume",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "Illume codebase dependency graph",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Illume - AI Powered Codebase Onboarding Platform",
    description:
      "Transform dense repositories into interactive onboarding guides. Architecture briefs, reading orders, glossaries, and ownership maps — all automated.",
    images: ["/og-image.png"],
  },
  alternates: {
    canonical: "https://illume.tejasnasa.me",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
    },
  },
};

/**
 * Root HTML shell: exposes the body and pixel fonts as CSS variables,
 * applies the global styles, and pins the starfield behind every page,
 * beneath any page's own background graph. Body text uses Geist; the `font-pixel` utility
 * switches labels and headings to Geist Pixel.
 *
 * @param children - Page content rendered inside the body.
 * @returns HTML document structure with SEO metadata applied.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistPixelSquare.variable} antialiased`}
    >
      <body className="min-h-screen bg-background text-foreground overflow-x-hidden">
        <Starfield className="-z-20" />
        {children}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@type": "WebApplication",
              name: "Illume",
              url: "https://illume.tejasnasa.me",
              description:
                "Transform dense repositories into interactive onboarding guides. Architecture briefs, reading orders, glossaries, and ownership maps — all automated.",
              applicationCategory: "DeveloperApplication",
              operatingSystem: "Web",
            }),
          }}
        />
      </body>
    </html>
  );
}
