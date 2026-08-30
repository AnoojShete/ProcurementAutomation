import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";

export function Drawer({
  open,
  onClose,
  title,
  children,
  side = "right",
}: {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  side?: "left" | "right";
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40" role="presentation">
      <div className="absolute inset-0 bg-slate-900/40 animate-fade-in" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        className={`absolute top-0 ${side === "right" ? "right-0" : "left-0"} h-full w-full max-w-sm bg-white shadow-popover animate-slide-in-right flex flex-col`}
      >
        {title && (
          <div className="flex items-center justify-between border-b border-surface-border px-4 py-3.5">
            <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
            <button onClick={onClose} aria-label="Close" className="rounded-md p-1 text-slate-400 hover:bg-surface-muted hover:text-slate-600">
              <X className="size-4" />
            </button>
          </div>
        )}
        <div className="flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
