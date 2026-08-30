import { cn } from "@/lib/cn";
import { formatRelativeTime } from "@/lib/format";
import type { RiskBand } from "@/types/api";

const BAND_COLOR: Record<string, string> = { Low: "bg-success-500", Medium: "bg-warning-500", High: "bg-danger-500" };

export function RiskGauge({ score, band, scoredAt }: { score: number; band: RiskBand; scoredAt?: string | null }) {
  const pct = Math.round(Math.min(Math.max(score, 0), 1) * 100);
  return (
    <div>
      <div className="flex items-end justify-between">
        <span className="text-3xl font-semibold tabular text-slate-900">{score.toFixed(2)}</span>
        <span className={cn("text-sm font-medium", band === "High" ? "text-danger-600" : band === "Medium" ? "text-warning-700" : "text-success-700")}>
          {band} Risk
        </span>
      </div>
      <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div className={cn("h-full rounded-full transition-all", BAND_COLOR[band] ?? "bg-slate-400")} style={{ width: `${pct}%` }} />
      </div>
      {scoredAt && <p className="mt-1.5 text-xs text-slate-400">Last calculated {formatRelativeTime(scoredAt)}</p>}
    </div>
  );
}
