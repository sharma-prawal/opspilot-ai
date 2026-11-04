import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";
import { AuthRedirect } from "@/components/auth-redirect";
import { Nav } from "@/components/nav";
import { Providers } from "./providers";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "OpsPilot AI",
  description: "Local-first agentic incident investigation",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full font-sans">
        <Providers>
          <header className="sticky top-0 z-10 border-b border-border bg-panel/90 backdrop-blur">
            <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-2.5">
              <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
                <span aria-hidden className="grid size-6 place-items-center rounded bg-accent text-xs font-bold text-white">OP</span>
                OpsPilot <span className="text-muted font-normal">AI</span>
              </Link>
              <Suspense fallback={<div className="h-8" />}>
                <Nav />
                <AuthRedirect />
              </Suspense>
            </div>
          </header>
          <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
