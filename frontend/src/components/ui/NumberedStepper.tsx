import { Check } from "lucide-react";
import { cn } from "@/lib/cn";

export function NumberedStepper({ steps, currentIndex }: { steps: string[]; currentIndex: number }) {
  return (
    <ol className="flex items-center">
      {steps.map((label, i) => {
        const state = i < currentIndex ? "completed" : i === currentIndex ? "current" : "upcoming";
        return (
          <li key={label} className={cn("flex items-center", i < steps.length - 1 && "flex-1")}>
            <div className="flex flex-col items-center gap-1.5">
              <div
                className={cn(
                  "flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                  state === "completed" && "bg-brand-600 text-white",
                  state === "current" && "bg-brand-600 text-white ring-4 ring-brand-100",
                  state === "upcoming" && "bg-slate-100 text-slate-400",
                )}
              >
                {state === "completed" ? <Check className="size-3.5" /> : i + 1}
              </div>
              <span className={cn("hidden text-xs sm:block", state === "upcoming" ? "text-slate-400" : "font-medium text-slate-700")}>
                {label}
              </span>
            </div>
            {i < steps.length - 1 && (
              <div className={cn("mx-2 h-0.5 flex-1", i < currentIndex ? "bg-brand-600" : "bg-slate-200")} />
            )}
          </li>
        );
      })}
    </ol>
  );
}
