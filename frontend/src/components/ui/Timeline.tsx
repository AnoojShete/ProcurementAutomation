import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface TimelineEvent {
  key: string;
  title: ReactNode;
  timestamp?: string | null;
  description?: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
  /** Who did it: a person or an agent ("Contract & Risk agent"). */
  actor?: ReactNode;
  /** A decision gets a stamp on the trail. */
  stamp?: "Approved" | "Rejected" | "Signed";
  /** Raw ISO time of the event; a stamp settles in only when it's fresh. */
  at?: string | null;
}

const dotTone: Record<NonNullable<TimelineEvent["tone"]>, string> = {
  neutral: "bg-sheet border-rule-strong",
  success: "bg-success-500 border-success-500",
  warning: "bg-warning-500 border-warning-500",
  danger: "bg-danger-500 border-danger-500",
};

const STAMP_TONE: Record<NonNullable<TimelineEvent["stamp"]>, string> = {
  Approved: "text-success-700 border-success-700",
  Signed: "text-accent border-accent",
  Rejected: "text-danger-600 border-danger-600",
};

const FRESH_MS = 2 * 60 * 1000;

/** The decision stamp: an inked mark that settles onto the trail (220 ms)
 * only when the decision just happened, never on a routine reload. */
export function Stamp({ label, at }: { label: NonNullable<TimelineEvent["stamp"]>; at?: string | null }) {
  const fresh = at ? Date.now() - new Date(at).getTime() < FRESH_MS : false;
  return (
    <span
      className={cn(
        "inline-flex -rotate-2 items-center rounded-sm border-2 px-1.5 py-px font-mono text-caption font-medium uppercase tracking-[0.08em]",
        STAMP_TONE[label],
        fresh && "animate-stamp",
      )}
    >
      {label}
    </span>
  );
}

/** The paper trail: a ruled spine of who did what, when. Used on every
 * item's home page and on dashboards. */
export function Timeline({ events }: { events: TimelineEvent[] }) {
  if (!events.length) return <p className="text-13 text-ink-3">No activity yet.</p>;
  return (
    <ol className="relative">
      {events.map((e, i) => (
        <li key={e.key} className="relative grid grid-cols-[14px_1fr] gap-x-3 pb-5 last:pb-0">
          {/* spine + dot */}
          <span className="relative flex justify-center" aria-hidden="true">
            {i < events.length - 1 && <span className="absolute bottom-[-20px] top-3 w-px bg-rule-mid" />}
            <span className={cn("relative mt-[5px] size-2.5 rounded-full border-2", dotTone[e.tone ?? "neutral"])} />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
              <p className="text-13 font-medium text-ink">{e.title}</p>
              {e.timestamp && <time className="text-caption tabular text-ink-3">{e.timestamp}</time>}
            </div>
            {e.actor && <p className="mt-0.5 text-caption text-ink-2">{e.actor}</p>}
            {e.description && <div className="mt-0.5 text-13 text-ink-3">{e.description}</div>}
            {e.stamp && (
              <div className="mt-1.5">
                <Stamp label={e.stamp} at={e.at} />
              </div>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
