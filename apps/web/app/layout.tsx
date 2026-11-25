import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";
import { AuthRedirect } from "@/components/auth-redirect";
import { Nav } from "@/components/nav";
import { BrandMark } from "@/components/brand";
import { Providers } from "./providers";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "OpsPilot AI — Incident Forensics Workbench",
  description:
    "Evidence-grounded autonomous incident investigation with deterministic safety gates, PostgreSQL tsvector and pgvector hybrid RAG, and authenticated human-in-the-loop approvals.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col font-sans bg-bg text-text selection:bg-accent-soft selection:text-accent">
        <a href="#main-content" className="skip-link">Skip to content</a>
        <Providers>
          <header className="sticky top-0 z-40 border-b border-border bg-panel">
            <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-2.5 sm:px-6">
              <div className="flex items-center gap-3">
                <Link
                  href="/"
                  aria-label="OpsPilot AI home"
                  className="group flex items-center gap-2.5 font-bold tracking-tight text-text hover:opacity-90 transition-opacity"
                >
                  <BrandMark />
                  <div className="flex items-baseline gap-1.5">
                    <span className="font-serif-heading text-lg font-bold tracking-tight text-text">
                      OpsPilot
                    </span>
                    <span className="font-mono text-xs font-bold text-accent tracking-wider">
                      AI
                    </span>
                  </div>
                </Link>


              </div>

              <Suspense fallback={<div className="h-8" />}>
                <Nav />
                <AuthRedirect />
              </Suspense>
            </div>
          </header>

          <main id="main-content" className="min-w-0 mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
            <Suspense>{children}</Suspense>
          </main>

          <footer className="border-t border-border bg-panel/60 py-6 text-xs text-muted">
            <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-4 sm:flex-row sm:px-6 font-mono text-[11px]">
              <div className="flex items-center gap-2">
                <span className="font-serif-heading font-bold text-text">OpsPilot AI</span>
                <span className="text-border-strong">|</span>
                <span>Incident forensics · local-first</span>
              </div>
              <div className="flex flex-wrap items-center gap-4 text-xs">
                <Link href="/architecture" className="hover:text-text transition-colors">
                  System Anatomy
                </Link>
                <Link href="/integrations" className="hover:text-text transition-colors">
                  Telemetry Sources
                </Link>
                <Link href="/safety" className="hover:text-text transition-colors">
                  Safety Gates &amp; HITL
                </Link>
                <Link href="/guide" className="hover:text-text transition-colors">
                  Field Guide
                </Link>
                <span className="text-text-muted">Evidence before action</span>
              </div>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
