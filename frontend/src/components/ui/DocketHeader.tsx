import { useState, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/cn";

/** A short reference ("PR-5c4d789f") that copies the full ID on click, so
 * pages never show a bare UUID but the full one is one click away. */
export function RefCopy({ prefix, id, className }: { prefix: string; id: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked (non-secure context); the title still shows the ID */
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      title={`Copy full ID: ${id}`}
      aria-label={copied ? "Copied full ID" : `Copy full ID ${id}`}
      className={cn(
        "-mx-1 inline-flex items-center gap-1 rounded-sm px-1 font-mono text-13 text-ink-3 transition-colors duration-1 hover:bg-sheet-sunk hover:text-ink",
        className,
      )}
    >
      {prefix}-{id.slice(0, 8)}
      {copied ? <Check className="size-3 text-success-600" aria-hidden="true" /> : <Copy className="size-3 opacity-60" aria-hidden="true" />}
    </button>
  );
}

/** The top of every item's home page: mono reference, serif title (the
 * only serif in the UI: "this is a document"), status, and the primary
 * action. A LedgerStrip of key figures usually follows it. */
export function DocketHeader({
  reference,
  title,
  status,
  meta,
  actions,
}: {
  reference?: ReactNode;
  title: ReactNode;
  status?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0 flex-1">
        {reference && <div className="flex flex-wrap items-center gap-x-3 gap-y-1">{reference}</div>}
        <h2
          className="mt-1 text-balance font-doc text-[1.375rem] font-semibold leading-7 tracking-[-0.01em] text-ink sm:text-doc-title"
          style={{ viewTransitionName: "docket-title" }}
        >
          {title}
        </h2>
        {(status || meta) && (
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-13 text-ink-2">
            {status}
            {meta}
          </div>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
