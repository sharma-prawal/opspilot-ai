import type { ButtonHTMLAttributes, ReactNode } from "react";
import { confidenceLabel, humanize, statusTone, type Tone } from "@/lib/format";

const TONES: Record<Tone, string> = {
  neutral: "bg-panel-2 text-muted border-border",
  info: "bg-info-soft text-info border-transparent",
  warn: "bg-warn-soft text-warn border-transparent",
  danger: "bg-danger-soft text-danger border-transparent",
  success: "bg-success-soft text-success border-transparent",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs font-medium whitespace-nowrap ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  const tone = statusTone(status);
  return (
    <Badge tone={tone}>
      <span aria-hidden className={`size-1.5 rounded-full ${tone === "neutral" ? "bg-muted" : "bg-current"}`} />
      {humanize(status)}
    </Badge>
  );
}

export function Card({ title, actions, children, className = "" }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`rounded-lg border border-border bg-panel ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Button({ variant = "secondary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger";
}) {
  const styles = {
    primary: "bg-accent text-white hover:opacity-90 border-transparent",
    secondary: "bg-panel text-text hover:bg-panel-2 border-border",
    danger: "bg-panel text-danger hover:bg-danger-soft border-border",
  }[variant];
  return (
    <button
      {...props}
      className={`inline-flex h-8 items-center justify-center gap-1.5 rounded-md border px-3 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
    />
  );
}

export function ConfidenceBar({ value }: { value: number }) {
  const label = confidenceLabel(value);
  const color = label === "high" ? "bg-success" : label === "medium" ? "bg-warn" : "bg-muted";
  return (
    <div className="flex items-center gap-2" aria-label={`confidence ${Math.round(value * 100)} percent (${label})`}>
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-panel-2">
        <div className={`h-full ${color}`} style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className="text-xs tabular-nums text-muted">{Math.round(value * 100)}% · {label}</span>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-muted">{children}</p>;
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
      {error instanceof Error ? error.message : String(error)}
    </p>
  );
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
