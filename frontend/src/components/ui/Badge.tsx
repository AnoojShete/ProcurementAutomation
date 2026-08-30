import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Circle, XCircle } from "lucide-react";
import { cn } from "@/lib/cn";

type Tone = "neutral" | "success" | "warning" | "danger" | "brand" | "intel";

const toneClasses: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-700",
  success: "bg-success-50 text-success-700",
  warning: "bg-warning-50 text-warning-700",
  danger: "bg-danger-50 text-danger-600",
  brand: "bg-brand-50 text-brand-700",
  intel: "bg-intel-50 text-intel-700",
};

export function Badge({ tone = "neutral", children, className, icon }: { tone?: Tone; children: ReactNode; className?: string; icon?: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        toneClasses[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

const REQUEST_STATUS_TONE: Record<string, Tone> = {
  pending_approval: "warning",
  approved: "success",
  rejected: "danger",
  fulfilled: "brand",
};

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const key = status ?? "";
  const tone = REQUEST_STATUS_TONE[key] ?? "neutral";
  const label = key
    ? key
        .split("_")
        .map((w) => w[0].toUpperCase() + w.slice(1))
        .join(" ")
    : "Unknown";
  const Icon = tone === "success" ? CheckCircle2 : tone === "danger" ? XCircle : tone === "warning" ? AlertTriangle : Circle;
  return (
    <Badge tone={tone} icon={<Icon className="size-3" />}>
      {label}
    </Badge>
  );
}

const RISK_TONE: Record<string, Tone> = { Low: "success", Medium: "warning", High: "danger" };

export function RiskBadge({ band }: { band: string | null | undefined }) {
  if (!band) return <Badge tone="neutral">Not scored</Badge>;
  return <Badge tone={RISK_TONE[band] ?? "neutral"}>{band} Risk</Badge>;
}

const CONTRACT_STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  pending_signature: "warning",
  signed: "success",
};

export function ContractStatusBadge({ status }: { status: string | null | undefined }) {
  const key = status ?? "";
  const tone = CONTRACT_STATUS_TONE[key] ?? "neutral";
  const label = key
    ? key
        .split("_")
        .map((w) => w[0].toUpperCase() + w.slice(1))
        .join(" ")
    : "Unknown";
  return <Badge tone={tone}>{label}</Badge>;
}

export function DocumentStatusBadge({ status, needsReview }: { status: string | null | undefined; needsReview?: boolean }) {
  if (needsReview) return <Badge tone="warning" icon={<AlertTriangle className="size-3" />}>Needs Review</Badge>;
  const tone: Tone = status === "classified" ? "success" : status === "failed" ? "danger" : "neutral";
  const label = status ? status[0].toUpperCase() + status.slice(1) : "Unknown";
  return <Badge tone={tone}>{label}</Badge>;
}
