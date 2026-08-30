import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { IconType } from "@/lib/roleNav";

type Tone = "neutral" | "success" | "warning" | "danger" | "brand";

const iconToneClasses: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-600",
  success: "bg-success-50 text-success-600",
  warning: "bg-warning-50 text-warning-600",
  danger: "bg-danger-50 text-danger-600",
  brand: "bg-brand-50 text-brand-700",
};

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
        "flex items-start justify-between gap-3 rounded-xl border border-surface-border bg-white p-4 text-left shadow-card",
        onClick && "cursor-pointer transition-shadow hover:shadow-popover",
      )}
    >
      <div className="min-w-0">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
        <div className="mt-1.5 text-2xl font-semibold tabular text-slate-900">{value}</div>
        {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
      </div>
      {Icon && (
        <div className={cn("flex size-9 shrink-0 items-center justify-center rounded-lg", iconToneClasses[tone])}>
          <Icon className="size-[18px]" />
        </div>
      )}
    </Comp>
  );
}
