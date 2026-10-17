import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { IconType } from "@/lib/roleNav";
import { Skeleton } from "./Skeleton";

type Tone = "neutral" | "success" | "warning" | "danger" | "brand";

// Only states that need a second look get colour, and never for a zero:
// "0 escalated" is good news, so it stays ink.
const valueToneClasses: Record<Tone, string> = {
  neutral: "text-ink",
  success: "text-ink",
  warning: "text-warning-700",
  danger: "text-danger-600",
  brand: "text-ink",
};

const isZero = (v: ReactNode) => v === 0 || v === "0" || v === "₹0";

/** One figure in a LedgerStrip: label above, the number below. */
export function MetricCard({
  label,
  value,
  icon: Icon,
  tone = "brand",
  hint,
  onClick,
}: {
  label: string;
  value: ReactNode;
  icon?: IconType;
  tone?: Tone;
  hint?: ReactNode;
  onClick?: () => void;
}) {
  const Comp = onClick ? "button" : "div";
  return (
    <Comp
      onClick={onClick}
      className={cn(
        "flex min-w-0 flex-col px-4 py-3 text-left shadow-[-1px_-1px_0_0_rgb(var(--rule))]",
        onClick && "cursor-pointer transition-colors duration-1 hover:bg-sheet-sunk",
      )}
    >
      <div className="flex items-start gap-1.5 text-13 text-ink-2">
        {Icon && <Icon className="mt-[3px] size-3.5 shrink-0 text-ink-3" strokeWidth={1.75} aria-hidden="true" />}
        <span className="min-w-0">{label}</span>
      </div>
      <div className={cn("mt-1 break-words text-[1.375rem] font-medium leading-7 tabular sm:text-figure", isZero(value) ? "text-ink" : valueToneClasses[tone])}>{value}</div>
      {hint && <div className="mt-0.5 text-caption text-ink-3">{hint}</div>}
    </Comp>
  );
}

const LG_COLS: Record<number, string> = {
  2: "lg:grid-cols-2",
  3: "lg:grid-cols-3",
  4: "lg:grid-cols-4",
  5: "lg:grid-cols-5",
  6: "lg:grid-cols-3 xl:grid-cols-6",
};

/** The ledger strip: one ruled row of 3–6 key figures, closed by the
 * accountant's double rule. Replaces rows of separate metric boxes. */
export function LedgerStrip({
  children,
  cols = 4,
  loading,
  label,
  className,
}: {
  children?: ReactNode;
  cols?: number;
  loading?: boolean;
  label?: string;
  className?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label ?? "Key figures"}
      aria-busy={loading || undefined}
      className={cn(
        "grid grid-cols-2 overflow-hidden border-t border-ink/70 rule-double sm:grid-cols-3",
        LG_COLS[cols] ?? "lg:grid-cols-4",
        className,
      )}
    >
      {loading
        ? Array.from({ length: cols }).map((_, i) => (
            <div key={i} className="px-4 py-3 shadow-[-1px_-1px_0_0_rgb(var(--rule))]">
              <Skeleton className="h-3.5 w-24" />
              <Skeleton className="mt-2.5 h-7 w-16" />
            </div>
          ))
        : children}
    </div>
  );
}
