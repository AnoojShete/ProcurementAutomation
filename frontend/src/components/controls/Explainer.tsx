/** Two-line framing at the top of each control: the gap, and the fix. */
export function Explainer({ problem, control }: { problem: string; control: string }) {
  return (
    <div className="grid grid-cols-1 gap-px overflow-hidden rounded-md border border-surface-border bg-surface-border text-13 md:grid-cols-2">
      <div className="bg-white px-4 py-3">
        <p className="text-xs font-semibold text-slate-500">The gap</p>
        <p className="mt-1 text-slate-700">{problem}</p>
      </div>
      <div className="bg-white px-4 py-3">
        <p className="text-xs font-semibold text-slate-500">The control</p>
        <p className="mt-1 text-slate-700">{control}</p>
      </div>
    </div>
  );
}
