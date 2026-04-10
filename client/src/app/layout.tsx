import { Toast } from "@/components/ui/Toast";
import type { Metadata } from "next";
import { Space_Grotesk } from "next/font/google";
import "./globals.css";

const spaceGrotesk = Space_Grotesk({
  variable: "--space-grotesk",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Illume — AI-Powered Repo Analyzer",
  description:
    "An elite-tier AI Code Analyzer with deterministic AST-first approach for hallucination-free querying and 3D architectural visualization.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${spaceGrotesk.className} antialiased`}>
      <body className="min-h-screen bg-background text-foreground overflow-x-hidden grid-bg">
        {children}
        <Toast />
      </body>
    </html>
  );
}
