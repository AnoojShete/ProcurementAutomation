import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

export interface AttentionItem {
  key: string;
  message: ReactNode;
  cta: string;
  to: string;
}

/** The "what should I do next" list — spec §38. Every item here must come
 * from real fetched data; an empty list renders nothing (no invented tasks). */
export function AttentionCard({ items }: { items: AttentionItem[] }) {
  if (!items.length) return null;
  return (
    <section className="rounded-md border border-surface-border bg-white">
      <div className="flex items-center gap-2 border-b border-surface-border px-4 py-2.5">
        <h2 className="text-sm font-semibold text-slate-900">Needs attention</h2>
        <span className="rounded-full bg-warning-50 px-1.5 text-xs font-medium leading-[18px] text-warning-700 ring-1 ring-inset ring-warning-500/40">
          {items.length}
        </span>
      </div>
      <ul className="divide-y divide-surface-border">
        {items.map((item) => (
          <li key={item.key}>
            <Link
              to={item.to}
              className="group flex items-center justify-between gap-3 px-4 py-2.5 text-13 hover:bg-surface-subtle"
            >
              <span className="flex items-start gap-2.5 text-slate-700">
                <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-warning-500" aria-hidden="true" />
                <span>{item.message}</span>
              </span>
              <span className="flex shrink-0 items-center gap-0.5 font-medium text-brand-700 group-hover:underline">
                {item.cta}
                <ChevronRight className="size-3.5" />
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
