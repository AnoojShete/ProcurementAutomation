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
              "relative flex items-center gap-1.5 px-3 py-2 text-sm transition-colors",
              isActive ? "font-semibold text-slate-900" : "text-slate-600 hover:text-slate-900",
            )}
          >
            {tab.label}
            {tab.count != null && (
              <span
                className={cn(
                  "rounded-full bg-surface-muted px-1.5 text-xs font-medium leading-[18px] tabular text-slate-700",
                )}
              >
                {tab.count}
              </span>
            )}
            {isActive && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand-500" />}
          </button>
        );
      })}
    </div>
  );
}
