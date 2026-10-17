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
      <div className="absolute inset-0 bg-ink/35 animate-fade-in" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        className={`absolute top-0 ${side === "right" ? "right-0" : "left-0"} h-full w-full max-w-sm bg-sheet shadow-popover animate-slide-in-right flex flex-col`}
      >
        {title && (
          <div className="flex items-center justify-between border-b border-rule px-4 py-3">
            <h2 className="text-heading font-semibold text-ink">{title}</h2>
            <button onClick={onClose} aria-label="Close" className="rounded p-1.5 text-ink-2 hover:bg-sheet-sunk hover:text-ink">
              <X className="size-4" />
            </button>
          </div>
        )}
        <div className="flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
