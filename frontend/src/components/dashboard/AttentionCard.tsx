import type { ReactNode } from "react";
import { ArrowRight, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

export interface AttentionItem {
  key: string;
  message: ReactNode;
  cta: string;
  to: string;
}

/** The "what should I do next" system — spec §38. Every item here must come
 * from real fetched data; an empty list renders nothing (no invented tasks). */
export function AttentionCard({ items }: { items: AttentionItem[] }) {
  if (!items.length) return null;
  return (
    <div className="rounded-xl border border-intel-100 bg-gradient-to-br from-intel-50 to-white p-4">
      <div className="mb-3 flex items-center gap-2">
        <Sparkles className="size-4 text-intel-600" />
        <h2 className="text-sm font-semibold text-intel-700">What needs your attention</h2>
      </div>
      <div className="flex flex-col gap-2">
        {items.map((item) => (
          <Link
            key={item.key}
            to={item.to}
            className="flex items-center justify-between gap-3 rounded-lg border border-intel-100 bg-white px-3.5 py-2.5 text-sm transition-colors hover:border-intel-300"
          >
            <span className="text-slate-700">{item.message}</span>
            <span className="flex shrink-0 items-center gap-1 font-medium text-intel-700">
              {item.cta}
              <ArrowRight className="size-3.5" />
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
