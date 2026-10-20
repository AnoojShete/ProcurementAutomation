import type { ReactNode } from "react";
import { Check, PackageCheck, X } from "lucide-react";
import { cn } from "@/lib/cn";

type Tone = "neutral" | "success" | "warning" | "danger" | "brand" | "intel" | "received";

// One tone map for every status in the app: tint fill, tone text (all ≥ 5.6 : 1).
const toneClasses: Record<Tone, string> = {
  neutral: "bg-sheet-sunk text-ink-2",
  success: "bg-success-50 text-success-700",
  warning: "bg-warning-50 text-warning-700",
  danger: "bg-danger-50 text-danger-600",
  brand: "bg-brand-50 text-brand-700",
  intel: "bg-sheet-sunk text-ink-2",
  received: "bg-received-tint text-received",
};

/** Leading glyph, so state never rides on colour alone:
 * ✓ done · ✕ failed · ● in progress / waiting · ○ neutral · package received. */
function Glyph({ tone }: { tone: Tone }) {
  if (tone === "received") return <PackageCheck className="size-3 shrink-0" strokeWidth={2.25} aria-hidden="true" />;
  if (tone === "success") return <Check className="size-3 shrink-0" strokeWidth={2.5} aria-hidden="true" />;
  if (tone === "danger") return <X className="size-3 shrink-0" strokeWidth={2.5} aria-hidden="true" />;
  if (tone === "neutral" || tone === "intel")
    return <span className="size-[7px] shrink-0 rounded-full border-[1.5px] border-current" aria-hidden="true" />;
  return <span className="size-[7px] shrink-0 rounded-full bg-current" aria-hidden="true" />;
}

/** Sentence case for API values like "active" or "signed", in CSS so the
 * text itself is unchanged. */
function Text({ children }: { children: ReactNode }) {
  return typeof children === "string" ? <span className="inline-block first-letter:uppercase">{children}</span> : <>{children}</>;
}

export function Badge({ tone = "neutral", children, className, icon }: { tone?: Tone; children: ReactNode; className?: string; icon?: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-sm px-1.5 text-caption font-medium",
        toneClasses[tone],
        className,
      )}
    >
      {icon}
      <Text>{children}</Text>
    </span>
  );
}

/** The status tag: same shape as Badge, always with its glyph. */
export function StatusDot({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1.5 whitespace-nowrap rounded-sm px-1.5 text-caption font-medium",
        toneClasses[tone],
      )}
    >
      <Glyph tone={tone} />
      <Text>{children}</Text>
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
  ordered: "brand",
  partially_received: "received",
  rejected: "danger",
  fulfilled: "received",
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
  return <StatusDot tone={RISK_TONE[band] ?? "neutral"}>{band} risk</StatusDot>;
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
