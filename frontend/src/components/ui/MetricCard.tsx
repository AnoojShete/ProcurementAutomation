import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { IconType } from "@/lib/roleNav";

type Tone = "neutral" | "success" | "warning" | "danger" | "brand";

// Only states that need a second look get colour; the rest stay neutral.
const valueToneClasses: Record<Tone, string> = {
  neutral: "text-slate-900",
  success: "text-slate-900",
  warning: "text-warning-700",
  danger: "text-danger-600",
  brand: "text-slate-900",
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
        "flex min-w-0 flex-col rounded-md border border-surface-border bg-white px-4 py-3 text-left",
        onClick && "cursor-pointer transition-colors hover:border-slate-400",
      )}
    >
      <div className="flex items-center gap-1.5 text-13 text-slate-600">
        {Icon && <Icon className="size-3.5 shrink-0 text-slate-400" strokeWidth={1.75} />}
        <span className="truncate">{label}</span>
      </div>
      <div className={cn("mt-1 text-2xl font-semibold leading-8 tabular", value === 0 ? "text-slate-900" : valueToneClasses[tone])}>
        {value}
      </div>
      {hint && <div className="mt-0.5 truncate text-xs text-slate-500">{hint}</div>}
    </Comp>
  );
}
