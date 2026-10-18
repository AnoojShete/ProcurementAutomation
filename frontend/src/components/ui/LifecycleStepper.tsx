import { Ban, Check, Loader2, PackageCheck, X } from "lucide-react";
import { cn } from "@/lib/cn";
import type { LifecycleStage } from "@/lib/lifecycle";

const STATE_TEXT: Record<LifecycleStage["state"], string> = {
  completed: "Done",
  current: "Current step",
  pending: "Not started",
  blocked: "Blocked",
  failed: "Failed",
};

/** The step marker. "Current" is a static filled ring (waiting on a person);
 * the spinner is reserved for `working`, when an agent is actually busy. */
function Marker({ stage, index }: { stage: LifecycleStage; index: number }) {
  const base = "relative z-10 flex size-7 shrink-0 items-center justify-center rounded-full";
  switch (stage.state) {
    case "completed":
      // Received goods get the "received" lavender, like the Fulfilled status.
      if (stage.key === "fulfillment")
        return (
          <span className={cn(base, "bg-received text-white")}>
            <PackageCheck className="size-3.5" strokeWidth={2.25} />
          </span>
        );
      return (
        <span className={cn(base, "bg-success-500 text-white")}>
          <Check className="size-3.5" strokeWidth={2.75} />
        </span>
      );
    case "current":
      return (
        <span className={cn(base, "border-2 border-accent bg-sheet text-accent")}>
          {stage.working ? <Loader2 className="size-3.5 animate-spin" /> : <span className="size-2.5 rounded-full bg-accent" />}
        </span>
      );
    case "failed":
      return (
        <span className={cn(base, "bg-danger-500 text-white")}>
          <X className="size-3.5" strokeWidth={2.75} />
        </span>
      );
    case "blocked":
      return (
        <span className={cn(base, "border border-rule-strong bg-sheet-sunk text-ink-3")}>
          <Ban className="size-3" />
        </span>
      );
    default:
      return (
        <span className={cn(base, "border border-rule-strong bg-sheet text-caption font-medium text-ink-3")}>{index + 1}</span>
      );
  }
}

const LABEL_TONE: Record<LifecycleStage["state"], string> = {
  completed: "text-ink",
  current: "font-semibold text-accent",
  pending: "text-ink-3",
  blocked: "text-ink-3",
  failed: "font-medium text-danger-600",
};

/** The procurement request lifecycle: created → document processing →
 * vendor validation → approval → inventory check → contract → signature →
 * fulfilment. With `onSelect`, each step is one button that opens its
 * details (and its action, e.g. approve or sign).
 *
 * ≥ sm: a horizontal track. Every step has the same structure (a connector
 * on both sides, transparent at the ends), so all labels share a baseline.
 * < sm: a vertical task list. */
export function LifecycleStepper({
  stages,
  onSelect,
  selectedKey,
}: {
  stages: LifecycleStage[];
  onSelect?: (stage: LifecycleStage) => void;
  selectedKey?: string | null;
}) {
  return (
    <ol className="flex flex-col sm:min-w-[640px] sm:flex-row sm:items-stretch">
      {stages.map((stage, i) => {
        const first = i === 0;
        const last = i === stages.length - 1;
        const selected = selectedKey === stage.key;
        // The connector into a step is solid once the previous step is done.
        const inDone = !first && stages[i - 1].state === "completed";
        const outDone = !last && stage.state === "completed";
        const descId = `stage-${stage.key}-desc`;

        const body = (
          <>
            {/* Track: connector · marker · connector */}
            <span className="flex w-auto flex-col items-center self-stretch sm:w-full sm:flex-row sm:self-auto" aria-hidden="true">
              <span className={cn("hidden h-0.5 flex-1 sm:block", first ? "bg-transparent" : inDone ? "bg-success-500" : "bg-rule")} />
              <Marker stage={stage} index={i} />
              <span className={cn("hidden h-0.5 flex-1 sm:block", last ? "bg-transparent" : outDone ? "bg-success-500" : "bg-rule")} />
              {/* vertical connector on phones */}
              <span className={cn("w-0.5 flex-1 sm:hidden", last ? "bg-transparent" : outDone ? "bg-success-500" : "bg-rule")} />
            </span>
            <span className="min-w-0 pb-4 pl-3 text-left sm:px-1.5 sm:pb-0 sm:pl-1.5 sm:pt-2 sm:text-center">
              <span className={cn("block text-13 leading-tight", LABEL_TONE[stage.state], onSelect && "group-hover:underline")}>
                {stage.label}
              </span>
              <span id={descId} className="mt-0.5 block text-caption text-ink-3">
                <span className="sr-only">{STATE_TEXT[stage.state]}. </span>
                {stage.detail}
              </span>
            </span>
          </>
        );

        return (
          <li key={stage.key} className="flex flex-1 sm:min-w-0">
            {onSelect ? (
              <button
                type="button"
                onClick={() => onSelect(stage)}
                aria-label={stage.label}
                aria-describedby={descId}
                aria-pressed={selected}
                aria-current={stage.state === "current" ? "step" : undefined}
                className={cn(
                  "group flex w-full rounded transition-colors duration-1 sm:flex-col sm:items-center sm:py-1.5",
                  "hover:bg-sheet-sunk focus-visible:ring-offset-0",
                  selected && "bg-accent-tint hover:bg-accent-tint",
                )}
              >
                {body}
              </button>
            ) : (
              <div className="flex w-full sm:flex-col sm:items-center sm:py-1.5" aria-current={stage.state === "current" ? "step" : undefined}>
                {body}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
