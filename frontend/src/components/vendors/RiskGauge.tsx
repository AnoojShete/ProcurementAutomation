import { cn } from "@/lib/cn";
import { formatRelativeTime } from "@/lib/format";
import type { RiskBand } from "@/types/api";

const BAND_COLOR: Record<string, string> = { Low: "bg-success-500", Medium: "bg-warning-500", High: "bg-danger-500" };

// score is null while checks are outstanding: show "Unrated" and the points
// found so far, never a number that looks like a rating.
export function RiskGauge({ score, band, scoredAt, pointsSoFar }: {
  score: number | null; band: RiskBand; scoredAt?: string | null; pointsSoFar?: number;
}) {
  const pct = score == null ? 0 : Math.round(Math.min(Math.max(score, 0), 1) * 100);
  return (
    <div>
      <div className="flex items-end justify-between">
        {score == null ? (
          <span className="text-3xl font-semibold text-ink-2">
            Unrated
            {pointsSoFar != null && (
              <span className="ml-2 text-sm font-normal text-ink-3">{pointsSoFar} points found so far</span>
            )}
          </span>
        ) : (
          <span className="text-3xl font-semibold tabular text-slate-900">{score.toFixed(2)}</span>
        )}
        <span className={cn("text-sm font-medium", band === "High" ? "text-danger-600" : band === "Medium" ? "text-warning-700" : "text-success-700")}>
          {score == null ? "Checks outstanding" : `${band} Risk`}
        </span>
      </div>
      <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div className={cn("h-full rounded-full transition-all", BAND_COLOR[band] ?? "bg-slate-400")} style={{ width: `${pct}%` }} />
      </div>
      {scoredAt && <p className="mt-1.5 text-xs text-slate-400">Last calculated {formatRelativeTime(scoredAt)}</p>}
    </div>
  );
}
