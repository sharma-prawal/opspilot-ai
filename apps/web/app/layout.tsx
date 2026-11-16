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
  title: "OpsPilot AI — Autonomous Incident Response",
  description:
    "Local-first agentic incident investigation with deterministic safety gates, hybrid RAG, and cryptographic human-in-the-loop approvals.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased dark`}
    >
      <body className="flex min-h-full flex-col font-sans bg-bg text-text selection:bg-accent/30 selection:text-white">
        <Providers>
          <header className="sticky top-0 z-40 border-b border-border bg-panel/90 backdrop-blur-md">
            <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-2.5 sm:px-6">
              <div className="flex items-center gap-3">
                <Link
                  href="/"
                  className="group flex items-center gap-2.5 font-bold tracking-tight text-text hover:opacity-90 transition-opacity"
                >
                  <span
                    aria-hidden
                    className="grid size-7 place-items-center rounded-lg bg-gradient-to-br from-accent to-blue-700 text-xs font-black text-white shadow-sm ring-1 ring-white/20"
                  >
                    OP
                  </span>
                  <div className="flex items-baseline gap-1.5">
                    <span className="text-base font-bold tracking-tight text-text">
                      OpsPilot
                    </span>
                    <span className="text-xs font-semibold text-accent uppercase tracking-wider">
                      AI
                    </span>
                  </div>
                </Link>
                <div className="hidden items-center gap-1.5 rounded-full border border-border bg-panel-2 px-2.5 py-0.5 text-[11px] text-muted md:flex">
                  <span aria-hidden className="size-1.5 rounded-full bg-accent" />
                  <span>Local Simulator</span>
                  <span className="text-border-strong">·</span>
                  <span className="text-text-muted">Isolated Demo Mode</span>
                </div>
              </div>

              <Suspense fallback={<div className="h-8" />}>
                <Nav />
                <AuthRedirect />
              </Suspense>
            </div>
          </header>

          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
            {children}
          </main>

          <footer className="border-t border-border bg-panel/40 py-6 text-xs text-muted">
            <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-4 sm:flex-row sm:px-6">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-text">OpsPilot AI</span>
                <span>— Local-first agentic incident response simulator.</span>
              </div>
              <div className="flex flex-wrap items-center gap-4 text-xs">
                <Link href="/architecture" className="hover:text-text transition-colors">
                  System Architecture
                </Link>
                <Link href="/integrations" className="hover:text-text transition-colors">
                  Integrations &amp; Sources
                </Link>
                <Link href="/safety" className="hover:text-text transition-colors">
                  Safety Gates &amp; HITL
                </Link>
                <Link href="/guide" className="hover:text-text transition-colors">
                  Developer Guide
                </Link>
                <span className="text-text-muted">No cloud inference · Port 127.0.0.1</span>
              </div>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
