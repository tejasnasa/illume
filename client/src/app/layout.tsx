import { Toast } from "@/components/ui/Toast";
import type { Metadata } from "next";
import { Space_Grotesk } from "next/font/google";
import "./globals.css";

const spaceGrotesk = Space_Grotesk({
  variable: "--space-grotesk",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Illume - AI Powered Codebase Onboarding Platform",
  description:
    "Transform dense repositories into interactive onboarding guides. Architecture briefs, reading orders, glossaries, and ownership maps — all automated.",
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
      </body>
    </html>
  );
}
