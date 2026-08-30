import { AlertOctagon, Ban, Check, Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";
import type { LifecycleStage } from "@/lib/lifecycle";

const STATE_STYLES: Record<LifecycleStage["state"], { dot: string; line: string; label: string }> = {
  completed: { dot: "bg-success-500 text-white", line: "bg-success-500", label: "text-slate-700" },
  current: { dot: "bg-brand-600 text-white ring-4 ring-brand-100", line: "bg-slate-200", label: "text-brand-700 font-semibold" },
  pending: { dot: "bg-slate-100 text-slate-400 border border-slate-300", line: "bg-slate-200", label: "text-slate-400" },
  blocked: { dot: "bg-slate-100 text-slate-400 border border-slate-300", line: "bg-slate-200", label: "text-slate-400" },
  failed: { dot: "bg-danger-500 text-white", line: "bg-slate-200", label: "text-danger-600 font-medium" },
};

function StageIcon({ state, index }: { state: LifecycleStage["state"]; index: number }) {
  if (state === "completed") return <Check className="size-3.5" />;
  if (state === "current") return <Loader2 className="size-3.5 animate-spin" />;
  if (state === "failed") return <AlertOctagon className="size-3.5" />;
  if (state === "blocked") return <Ban className="size-3 opacity-60" />;
  return <span className="text-[11px] font-medium">{index + 1}</span>;
}

/** The procurement request lifecycle — spec's key differentiator: created ->
 * document processing -> vendor validation -> approval -> inventory check ->
 * contract -> signature -> fulfillment. */
export function LifecycleStepper({ stages }: { stages: LifecycleStage[] }) {
  return (
    <div className="flex flex-col gap-0 sm:flex-row sm:items-start">
      {stages.map((stage, i) => {
        const styles = STATE_STYLES[stage.state];
        const isLast = i === stages.length - 1;
        return (
          <div key={stage.key} className="flex flex-1 sm:flex-col">
            <div className="flex flex-col items-center sm:w-full">
              <div className="flex w-full items-center sm:contents">
                <div className={cn("flex size-7 shrink-0 items-center justify-center rounded-full", styles.dot)}>
                  <StageIcon state={stage.state} index={i} />
                </div>
                {!isLast && (
                  <div
                    className={cn(
                      "mx-2 h-0.5 flex-1 sm:mx-0 sm:my-2 sm:h-0.5 sm:w-full",
                      styles.line,
                    )}
                  />
                )}
              </div>
            </div>
            <div className="py-2 pl-3 sm:px-1 sm:pl-0 sm:text-center">
              <p className={cn("text-xs leading-tight", styles.label)}>{stage.label}</p>
              {stage.detail && <p className="mt-0.5 text-[11px] text-slate-400">{stage.detail}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
