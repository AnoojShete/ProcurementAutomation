import { cn } from "@/lib/cn";

export interface TabItem {
  key: string;
  label: string;
  count?: number;
}

export function Tabs({ tabs, active, onChange }: { tabs: TabItem[]; active: string; onChange: (key: string) => void }) {
  return (
    <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-rule scrollbar-thin">
      {tabs.map((tab) => {
        const isActive = tab.key === active;
        return (
          <button
            key={tab.key}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.key)}
            className={cn(
              "relative flex h-10 shrink-0 items-center gap-1.5 px-3 text-sm transition-colors duration-1",
              isActive ? "font-medium text-ink" : "text-ink-2 hover:text-ink",
            )}
          >
            {tab.label}
            {tab.count != null && (
              <span
                className={cn(
                  "rounded-sm bg-sheet-sunk px-1.5 text-caption font-medium leading-[18px] tabular text-ink-2",
                )}
              >
                {tab.count}
              </span>
            )}
            {isActive && <span className="absolute inset-x-2 -bottom-px h-0.5 bg-accent" aria-hidden="true" />}
          </button>
        );
      })}
    </div>
  );
}
