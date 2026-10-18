import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { SYSTEM_SECTIONS } from "@/lib/roleNav";

/** Admin system management in one place: a card per section, each opening
 * that section's own page. */
export function SystemPage() {
  usePageHeader("System");
  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {SYSTEM_SECTIONS.map((s) => (
        <li key={s.to}>
          <Link
            to={s.to}
            className="group flex h-full items-start gap-3 rounded border border-rule bg-sheet px-4 py-4 transition-colors duration-1 hover:border-rule-strong hover:bg-sheet-sunk"
          >
            <s.icon className="mt-0.5 size-5 shrink-0 text-accent" strokeWidth={1.75} aria-hidden="true" />
            <span className="min-w-0 flex-1">
              <span className="block text-heading font-semibold text-ink">{s.label}</span>
              <span className="mt-0.5 block text-13 text-ink-3">{s.description}</span>
            </span>
            <ChevronRight className="mt-1 size-4 shrink-0 text-ink-3 group-hover:text-ink" aria-hidden="true" />
          </Link>
        </li>
      ))}
    </ul>
  );
}
