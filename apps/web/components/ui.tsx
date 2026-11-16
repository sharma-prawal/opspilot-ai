"use client";

import {
  type ButtonHTMLAttributes,
  type ReactNode,
  useState,
} from "react";
import { confidenceLabel, humanize, statusTone, type Tone } from "@/lib/format";

export type ExtendedTone = Tone | "cyan" | "purple";

const TONES: Record<ExtendedTone, string> = {
  neutral: "bg-panel-2 text-text-muted border-border",
  info: "bg-info-soft text-info border-info/30",
  warn: "bg-warn-soft text-warn border-warn/30",
  danger: "bg-danger-soft text-danger border-danger/30",
  success: "bg-success-soft text-success border-success/30",
  cyan: "bg-info-soft text-info border-info/30",
  purple: "bg-purple-soft text-purple border-purple/30",
};

export function Badge({
  tone = "neutral",
  children,
  className = "",
}: {
  tone?: ExtendedTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium tracking-tight whitespace-nowrap ${TONES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

const ACTIVE_PULSES = new Set(["investigating", "running", "awaiting_approval", "queued", "pending", "executing"]);

export function StatusBadge({
  status,
  className = "",
}: {
  status: string | null | undefined;
  className?: string;
}) {
  if (!status) return null;
  const tone = statusTone(status);
  const isPulsing = ACTIVE_PULSES.has(status);

  return (
    <Badge tone={tone} className={className}>
      <span
        aria-hidden
        className={`size-1.5 rounded-full ${
          isPulsing ? "animate-pulse" : ""
        } ${
          tone === "neutral"
            ? "bg-muted"
            : tone === "success"
            ? "bg-success"
            : tone === "danger"
            ? "bg-danger"
            : tone === "warn"
            ? "bg-warn"
            : "bg-info"
        }`}
      />
      <span>{humanize(status)}</span>
    </Badge>
  );
}

export function SeverityBadge({ severity }: { severity: string | null | undefined }) {
  if (!severity) return null;
  const s = severity.toLowerCase();
  const tone: Tone =
    s === "critical" || s === "p0" || s === "sev0"
      ? "danger"
      : s === "high" || s === "p1" || s === "sev1"
      ? "danger"
      : s === "medium" || s === "p2" || s === "sev2"
      ? "warn"
      : "info";

  return (
    <Badge tone={tone} className="font-semibold uppercase tracking-wider text-[10px]">
      <span aria-hidden className="size-1.5 rounded-full bg-current" />
      {severity}
    </Badge>
  );
}

export function Card({
  id,
  title,
  subtitle,
  actions,
  children,
  className = "",
  headerClassName = "",
}: {
  id?: string;
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  headerClassName?: string;
}) {
  return (
    <section id={id} className={`rounded-xl border border-border bg-panel shadow-sm transition-all ${className}`}>
      {(title || actions || subtitle) && (
        <header className={`flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3.5 ${headerClassName}`}>
          <div>
            {title && <h2 className="text-sm font-semibold tracking-tight text-text">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function StatCard({
  label,
  value,
  subtitle,
  tone = "neutral",
  icon,
  badge,
}: {
  label: string;
  value: string | number;
  subtitle?: string;
  tone?: "neutral" | "info" | "warn" | "danger" | "success";
  icon?: ReactNode;
  badge?: ReactNode;
}) {
  const toneColors = {
    neutral: "text-text border-border",
    info: "text-info border-info/30",
    warn: "text-warn border-warn/30",
    danger: "text-danger border-danger/30",
    success: "text-success border-success/30",
  }[tone];

  return (
    <div className="group relative rounded-xl border border-border bg-panel p-4 shadow-sm transition-all hover:border-border-strong hover:bg-panel/80">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wider text-muted">{label}</span>
        {icon && <span className="text-muted group-hover:text-text">{icon}</span>}
        {badge}
      </div>
      <div className={`mt-2 text-2xl font-bold tracking-tight tabular-nums sm:text-3xl ${toneColors}`}>
        {value}
      </div>
      {subtitle && <p className="mt-1 text-xs text-muted">{subtitle}</p>}
    </div>
  );
}

export function Button({
  variant = "secondary",
  size = "md",
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost" | "outline";
  size?: "sm" | "md" | "lg";
}) {
  const variantStyles = {
    primary:
      "bg-accent text-white shadow-sm hover:bg-accent-hover hover:shadow border-transparent focus:ring-2 focus:ring-accent/40",
    secondary:
      "bg-panel text-text hover:bg-panel-2 border-border hover:border-border-strong focus:ring-2 focus:ring-accent/20",
    danger:
      "bg-danger-soft text-danger hover:bg-danger hover:text-white border-danger/40 transition-colors focus:ring-2 focus:ring-danger/20",
    ghost:
      "bg-transparent text-muted hover:text-text hover:bg-panel-2 border-transparent",
    outline:
      "bg-transparent text-text hover:bg-panel-2 border-border hover:border-border-strong",
  }[variant];

  const sizeStyles = {
    sm: "h-7 px-2.5 text-xs rounded-md gap-1",
    md: "h-8.5 px-3.5 text-sm rounded-lg gap-2",
    lg: "h-10 px-4 text-base rounded-lg gap-2.5",
  }[size];

  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center font-medium transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-40 cursor-pointer ${variantStyles} ${sizeStyles} ${className}`}
    >
      {children}
    </button>
  );
}

export function ConfidenceBar({ value }: { value: number }) {
  const label = confidenceLabel(value);
  const color =
    label === "high"
      ? "bg-success"
      : label === "medium"
      ? "bg-warn"
      : "bg-danger";
  const percentage = Math.round(value * 100);

  return (
    <div
      className="flex items-center gap-2.5"
      aria-label={`confidence ${percentage} percent (${label})`}
    >
      <div className="h-2 w-28 overflow-hidden rounded-full bg-panel-2 border border-border">
        <div
          className={`h-full ${color} transition-all duration-500`}
          style={{ width: `${Math.max(4, Math.min(100, percentage))}%` }}
        />
      </div>
      <span className="text-xs font-mono font-medium tabular-nums text-text-muted">
        {percentage}%
      </span>
      <span
        className={`text-[11px] font-semibold uppercase tracking-wider ${
          label === "high"
            ? "text-success"
            : label === "medium"
            ? "text-warn"
            : "text-muted"
        }`}
      >
        {label}
      </span>
    </div>
  );
}

export function Empty({
  children,
  icon,
  action,
}: {
  children: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-10 text-center">
      {icon ? (
        <div className="mb-3 grid size-10 place-items-center rounded-full bg-panel-2 text-muted">
          {icon}
        </div>
      ) : (
        <div className="mb-2 text-2xl text-muted">∅</div>
      )}
      <p className="max-w-md text-sm text-muted">{children}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div
      role="alert"
      className="mb-4 flex items-start gap-2.5 rounded-lg border border-danger/30 bg-danger-soft px-3.5 py-2.5 text-sm text-danger"
    >
      <span className="font-bold">✕</span>
      <div className="min-w-0 flex-1 break-words">{msg}</div>
    </div>
  );
}

export function KV({
  items,
  dense = false,
}: {
  items: [string, ReactNode][];
  dense?: boolean;
}) {
  return (
    <dl
      className={`grid grid-cols-[max-content_1fr] gap-x-4 ${
        dense ? "gap-y-1 text-xs" : "gap-y-2 text-sm"
      }`}
    >
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted font-medium select-none">{k}</dt>
          <dd className="min-w-0 break-words text-text font-normal">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
  badge,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  badge?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-border pb-5">
      <div>
        <div className="flex items-center gap-2.5">
          <h1 className="text-xl font-bold tracking-tight text-text sm:text-2xl">
            {title}
          </h1>
          {badge}
        </div>
        {subtitle && <div className="mt-1 text-sm text-muted">{subtitle}</div>}
      </div>
      {actions && (
        <div className="flex flex-wrap items-center gap-2 sm:shrink-0">{actions}</div>
      )}
    </div>
  );
}

export function CodeBlock({
  code,
  language = "bash",
}: {
  code: string;
  language?: string;
}) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard write failed */
    }
  };

  return (
    <div className="group relative my-3 overflow-hidden rounded-lg border border-border bg-panel-2 font-mono text-xs">
      <div className="flex items-center justify-between border-b border-border/60 bg-panel px-3 py-1.5 text-[11px] text-muted">
        <span className="uppercase tracking-wider">{language}</span>
        <button
          onClick={copy}
          className="rounded px-2 py-0.5 text-muted hover:text-text hover:bg-panel-2 transition-colors cursor-pointer"
        >
          {copied ? "✓ Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-3.5 text-text leading-relaxed">
        <code>{code}</code>
      </pre>
    </div>
  );
}
