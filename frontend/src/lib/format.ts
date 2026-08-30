export function formatCurrency(amount: number | null | undefined, currency = "INR"): string {
  if (amount == null) return "—";
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${currency} ${amount.toLocaleString("en-IN")}`;
  }
}

export function formatDate(value: string | null | undefined, opts?: Intl.DateTimeFormatOptions): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-IN", opts ?? { day: "numeric", month: "short", year: "numeric" });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

export function formatRelativeTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  const diffMs = d.getTime() - Date.now();
  const diffSec = Math.round(diffMs / 1000);
  const abs = Math.abs(diffSec);
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (abs < 60) return rtf.format(diffSec, "second");
  if (abs < 3600) return rtf.format(Math.round(diffSec / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diffSec / 3600), "hour");
  if (abs < 2592000) return rtf.format(Math.round(diffSec / 86400), "day");
  return formatDate(value);
}

export function formatCountdown(deadline: string | null | undefined): { label: string; overdue: boolean } | null {
  if (!deadline) return null;
  const target = new Date(deadline).getTime();
  if (Number.isNaN(target)) return null;
  const diffMs = target - Date.now();
  const overdue = diffMs < 0;
  const abs = Math.abs(diffMs);
  const hours = Math.floor(abs / 3600000);
  const minutes = Math.floor((abs % 3600000) / 60000);
  const label = hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
  return { label: overdue ? `Overdue by ${label}` : `${label} left`, overdue };
}

export function formatConfidence(score: number | null | undefined): string {
  if (score == null) return "—";
  return `${Math.round(score * 100)}%`;
}

export function formatPercent(value: number | null | undefined, fractionDigits = 0): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(fractionDigits)}%`;
}

const DOCUMENT_TYPE_LABELS: Record<string, string> = { po: "PO", invoice: "Invoice", quote: "Quote" };

export function documentTypeLabel(value: string | null | undefined): string {
  if (!value) return "Unclassified";
  return DOCUMENT_TYPE_LABELS[value] ?? titleCase(value);
}

export function titleCase(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  const parts = name.split(/[@\s.]+/).filter(Boolean);
  return parts.slice(0, 2).map((p) => p[0]?.toUpperCase() ?? "").join("");
}
