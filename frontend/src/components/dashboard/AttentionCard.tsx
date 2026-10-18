import type { ReactNode } from "react";
import { CheckCircle2, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

export interface AttentionItem {
  key: string;
  message: ReactNode;
  cta: string;
  to: string;
}

/** The "what should I do next" list (spec §38), always first on a
 * dashboard. Every item comes from real fetched data; an empty list is a
 * single neutral line, never invented tasks. */
export function AttentionCard({ items }: { items: AttentionItem[] }) {
  if (!items.length) {
    return (
      <p className="flex items-center gap-2 border-y border-rule py-2.5 text-13 text-ink-2">
        <CheckCircle2 className="size-4 text-success-600" strokeWidth={1.75} aria-hidden="true" />
        Nothing needs you today.
      </p>
    );
  }
  return (
    <section aria-labelledby="attention-title" className="rounded border border-rule border-l-[3px] border-l-warning-500 bg-sheet">
      <div className="flex items-center gap-2 border-b border-rule px-4 py-2.5">
        <h2 id="attention-title" className="text-heading font-semibold text-ink">
          Needs attention
        </h2>
        <span className="rounded-sm bg-warning-50 px-1.5 text-caption font-medium leading-5 tabular text-warning-700">
          {items.length}
        </span>
      </div>
      <ul className="divide-y divide-rule">
        {items.map((item) => (
          <li key={item.key}>
            <Link
              to={item.to}
              className="group flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-2.5 text-sm transition-colors duration-1 hover:bg-sheet-sunk focus-visible:ring-inset focus-visible:ring-offset-0"
            >
              <span className="flex min-w-0 items-start gap-2.5 text-ink">
                <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-warning-500" aria-hidden="true" />
                <span>{item.message}</span>
              </span>
              <span className="ml-4 flex shrink-0 items-center gap-0.5 text-13 font-medium text-accent group-hover:underline">
                {item.cta}
                <ChevronRight className="size-3.5" aria-hidden="true" />
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
