import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/cn";
import { formatConfidence } from "@/lib/format";
import { CONFIDENCE_REVIEW_THRESHOLD } from "@/lib/constants";

export function ConfidenceIndicator({ score, compact }: { score: number | null | undefined; compact?: boolean }) {
  if (score == null) return <span className="text-xs text-slate-400">No confidence score</span>;
  const needsReview = score < CONFIDENCE_REVIEW_THRESHOLD;
  const barColor = needsReview ? "bg-warning-500" : "bg-success-500";
  const textColor = needsReview ? "text-warning-700" : "text-success-700";

  return (
    <div className={cn("flex items-center gap-2", compact ? "w-28" : "w-40")}>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
        <div className={cn("h-full rounded-full", barColor)} style={{ width: `${Math.round(score * 100)}%` }} />
      </div>
      <span className={cn("shrink-0 text-xs font-medium tabular", textColor)}>{formatConfidence(score)}</span>
      {needsReview && <AlertTriangle className="size-3.5 shrink-0 text-warning-500" aria-label="Needs review" />}
    </div>
  );
}
