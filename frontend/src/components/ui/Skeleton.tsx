import { cn } from "@/lib/cn";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-sm bg-rule/70", className)} aria-hidden="true" />;
}

/** Placeholder for one ledger-strip figure (same padding as MetricCard). */
export function SkeletonCard() {
  return (
    <div className="px-4 py-3">
      <Skeleton className="h-3.5 w-24" />
      <Skeleton className="mt-2.5 h-7 w-16" />
    </div>
  );
}

/** Rows of the real table height (36px), so nothing jumps when data lands. */
export function SkeletonTable({ rows = 5, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="w-full" role="status" aria-label="Loading">
      <div className="flex h-9 items-center gap-4 border-b border-rule bg-sheet-sunk px-3">
        {Array.from({ length: cols }).map((_, i) => (
          <Skeleton key={i} className="h-3 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex h-9 items-center gap-4 border-b border-rule px-3">
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton key={c} className="h-3 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}
