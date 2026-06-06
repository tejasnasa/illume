import { Toast } from "@/components/ui/Toast";
import type { Metadata } from "next";
import { Space_Grotesk } from "next/font/google";
import "./globals.css";

const spaceGrotesk = Space_Grotesk({
  variable: "--space-grotesk",
  subsets: ["latin"],
});

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

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${spaceGrotesk.className} antialiased`}>
      <body className="min-h-screen bg-background text-foreground overflow-x-hidden">
        {children}
        <Toast />
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
