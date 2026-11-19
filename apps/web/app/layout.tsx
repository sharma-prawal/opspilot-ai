import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";
import { AuthRedirect } from "@/components/auth-redirect";
import { Nav } from "@/components/nav";
import { ModelName } from "@/lib/models";
import { Providers } from "./providers";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "OpsPilot AI — Incident Forensics Workbench",
  description:
    "Evidence-grounded autonomous incident investigation with deterministic safety gates, hybrid pgvector RAG, and cryptographic human-in-the-loop approvals.",
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
        <Providers>
          <header className="sticky top-0 z-40 border-b border-border bg-panel/95 backdrop-blur-md">
            <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-2.5 sm:px-6">
              <div className="flex items-center gap-3">
                <Link
                  href="/"
                  className="group flex items-center gap-2.5 font-bold tracking-tight text-text hover:opacity-90 transition-opacity"
                >
                  <span
                    aria-hidden
                    className="grid size-7 place-items-center rounded-[3px] border border-border-strong bg-panel-2 font-serif-heading text-xs font-bold text-accent shadow-2xs"
                  >
                    OP
                  </span>
                  <div className="flex items-baseline gap-1.5">
                    <span className="font-serif-heading text-lg font-bold tracking-tight text-text">
                      OpsPilot
                    </span>
                    <span className="font-mono text-xs font-bold text-accent tracking-wider">
                      AI
                    </span>
                  </div>
                </Link>

                <div className="hidden items-center gap-1.5 rounded-[3px] border border-border bg-panel-2 px-2.5 py-0.5 font-mono text-[11px] text-muted md:flex">
                  <span className="text-text-muted">Incident Forensics Workbench</span>
                  <span className="text-border-strong">·</span>
                  <span className="text-text-muted">Model:</span>
                  <ModelName className="font-semibold text-text" />
                </div>
              </div>

              <Suspense fallback={<div className="h-8" />}>
                <Nav />
                <AuthRedirect />
              </Suspense>
            </div>
          </header>

          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
            <Suspense>{children}</Suspense>
          </main>

          <footer className="border-t border-border bg-panel/60 py-6 text-xs text-muted">
            <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-4 sm:flex-row sm:px-6 font-mono text-[11px]">
              <div className="flex items-center gap-2">
                <span className="font-serif-heading font-bold text-text">OpsPilot AI</span>
                <span className="text-border-strong">|</span>
                <span>Autonomous Incident Forensics &amp; Causal Verification</span>
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
                <span className="text-text-muted">Local Ollama · Port 127.0.0.1</span>
              </div>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
