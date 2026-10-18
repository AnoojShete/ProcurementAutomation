import { X } from "lucide-react";

/** "Showing: High risk ×": the filter a list was opened with (usually from
 * a dashboard figure), and one click back to the whole list. */
export function FilterChip({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-sm bg-accent-tint px-2 py-1 text-13 text-ink">
      <span className="first-letter:uppercase">{label}</span>
      <button type="button" onClick={onClear} className="rounded-sm p-0.5 text-ink-2 hover:text-ink" aria-label="Clear filter" title="Clear filter">
        <X className="size-3.5" aria-hidden="true" />
      </button>
    </span>
  );
}
