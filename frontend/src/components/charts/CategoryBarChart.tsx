// A single-series magnitude comparison (spend by category/vendor) — one
// hue, thin bars, direct value labels, sorted by magnitude. No categorical
// palette needed since there's only one series to distinguish.
export function CategoryBarChart({
  data,
  valueFormatter = (v) => String(v),
}: {
  data: { label: string; value: number }[];
  valueFormatter?: (value: number) => string;
}) {
  const sorted = [...data].sort((a, b) => b.value - a.value);
  const max = Math.max(...sorted.map((d) => d.value), 1);

  return (
    <div className="flex flex-col gap-3">
      {sorted.map((d) => (
        <div key={d.label} className="flex items-center gap-3">
          <span className="w-28 shrink-0 truncate text-sm capitalize text-slate-600">{d.label}</span>
          <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-brand-500"
              style={{ width: `${Math.max((d.value / max) * 100, 2)}%` }}
            />
          </div>
          <span className="w-24 shrink-0 text-right text-sm font-medium tabular text-slate-800">
            {valueFormatter(d.value)}
          </span>
        </div>
      ))}
    </div>
  );
}
