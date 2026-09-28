import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Tone = "neutral" | "success" | "warning" | "danger" | "brand" | "intel";

const toneClasses: Record<Tone, string> = {
  neutral: "border-surface-border bg-surface-subtle text-slate-700",
  success: "border-success-500/30 bg-success-50 text-success-700",
  warning: "border-warning-500/40 bg-warning-50 text-warning-700",
  danger: "border-danger-500/30 bg-danger-50 text-danger-600",
  brand: "border-brand-500/30 bg-brand-50 text-brand-800",
  intel: "border-surface-border bg-surface-subtle text-slate-700",
};

const dotClasses: Record<Tone, string> = {
  neutral: "bg-slate-400",
  success: "bg-success-500",
  warning: "bg-warning-500",
  danger: "bg-danger-500",
  brand: "bg-brand-500",
  intel: "bg-slate-400",
};

export function Badge({ tone = "neutral", children, className, icon }: { tone?: Tone; children: ReactNode; className?: string; icon?: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1 whitespace-nowrap rounded border px-1.5 text-xs font-medium",
        toneClasses[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

/** Status label with a coloured dot — the colour carries the state, the
 * text stays readable. */
export function StatusDot({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-13 text-slate-700">
      <span className={cn("size-2 shrink-0 rounded-full", dotClasses[tone])} aria-hidden="true" />
      {children}
    </span>
  );
}

function label(key: string): string {
  return key
    ? key
        .split("_")
        .map((w, i) => (i === 0 ? w[0].toUpperCase() + w.slice(1) : w))
        .join(" ")
    : "Unknown";
}

const REQUEST_STATUS_TONE: Record<string, Tone> = {
  pending_approval: "warning",
  approved: "success",
  rejected: "danger",
  fulfilled: "brand",
  partially_invoiced: "brand",
  invoice_received: "success",
};

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const key = status ?? "";
  return <StatusDot tone={REQUEST_STATUS_TONE[key] ?? "neutral"}>{label(key)}</StatusDot>;
}

const RISK_TONE: Record<string, Tone> = { Low: "success", Medium: "warning", High: "danger" };

export function RiskBadge({ band }: { band: string | null | undefined }) {
  if (!band) return <Badge tone="neutral">Not scored</Badge>;
  return <Badge tone={RISK_TONE[band] ?? "neutral"}>{band} risk</Badge>;
}

const CONTRACT_STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  pending_signature: "warning",
  signed: "success",
};

export function ContractStatusBadge({ status }: { status: string | null | undefined }) {
  const key = status ?? "";
  return <StatusDot tone={CONTRACT_STATUS_TONE[key] ?? "neutral"}>{label(key)}</StatusDot>;
}

export function DocumentStatusBadge({ status, needsReview }: { status: string | null | undefined; needsReview?: boolean }) {
  if (needsReview) return <StatusDot tone="warning">Needs review</StatusDot>;
  const tone: Tone =
    status === "classified" ? "success" : status === "failed" ? "danger" : status === "processing" ? "brand" : "neutral";
  return <StatusDot tone={tone}>{status ? status[0].toUpperCase() + status.slice(1) : "Unknown"}</StatusDot>;
}
