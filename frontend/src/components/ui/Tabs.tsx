import { cn } from "@/lib/cn";

export interface TabItem {
  key: string;
  label: string;
  count?: number;
}

export function Tabs({ tabs, active, onChange }: { tabs: TabItem[]; active: string; onChange: (key: string) => void }) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-surface-border">
      {tabs.map((tab) => {
        const isActive = tab.key === active;
        return (
          <button
            key={tab.key}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.key)}
            className={cn(
              "relative flex items-center gap-1.5 px-3 py-2.5 text-sm font-medium transition-colors",
              isActive ? "text-brand-700" : "text-slate-500 hover:text-slate-800",
            )}
          >
            {tab.label}
            {tab.count != null && (
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-xs tabular",
                  isActive ? "bg-brand-50 text-brand-700" : "bg-slate-100 text-slate-500",
                )}
              >
                {tab.count}
              </span>
            )}
            {isActive && <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-brand-600" />}
          </button>
        );
      })}
    </div>
  );
}
