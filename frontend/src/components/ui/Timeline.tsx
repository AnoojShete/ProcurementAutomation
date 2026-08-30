import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface TimelineEvent {
  key: string;
  title: ReactNode;
  timestamp?: string | null;
  description?: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
}

const dotTone: Record<NonNullable<TimelineEvent["tone"]>, string> = {
  neutral: "bg-slate-300",
  success: "bg-success-500",
  warning: "bg-warning-500",
  danger: "bg-danger-500",
};

export function Timeline({ events }: { events: TimelineEvent[] }) {
  if (!events.length) return <p className="text-sm text-slate-500">No activity yet.</p>;
  return (
    <ol className="relative ml-1.5 border-l border-surface-border">
      {events.map((e) => (
        <li key={e.key} className="relative pb-6 pl-5 last:pb-0">
          <span
            className={cn("absolute -left-[5px] top-1 size-2.5 rounded-full ring-4 ring-white", dotTone[e.tone ?? "neutral"])}
          />
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
            <p className="text-sm font-medium text-slate-800">{e.title}</p>
            {e.timestamp && <span className="text-xs text-slate-400">{e.timestamp}</span>}
          </div>
          {e.description && <p className="mt-0.5 text-sm text-slate-500">{e.description}</p>}
        </li>
      ))}
    </ol>
  );
}
