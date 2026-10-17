import { Link, NavLink, matchPath, useLocation } from "react-router-dom";
import { ChevronsLeft, LogOut } from "lucide-react";
import { cn } from "@/lib/cn";
import { useAuth } from "@/hooks/useAuth";
import { ROLE_LABELS, ROLE_NAV } from "@/lib/roleNav";
import { initials } from "@/lib/format";

export function Sidebar({
  collapsed,
  onToggleCollapse,
  mobileOpen,
  onCloseMobile,
}: {
  collapsed: boolean;
  onToggleCollapse: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}) {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  if (!user) return null;
  const items = ROLE_NAV[user.role];
  // Only the most specific matching item is active: on /app/requests/new,
  // "New Request" and not also "My Requests".
  const activeTo = items
    .filter((item) => matchPath({ path: item.to, end: item.end ?? false }, pathname))
    .sort((a, b) => b.to.length - a.to.length)[0]?.to;

  const content = (
    <div className="flex h-full flex-col border-r border-rule bg-paper">
      {/* Wordmark: the name over the accountant's double rule. */}
      <div className={cn("flex h-14 items-center border-b border-rule px-4", collapsed && "justify-center px-2")}>
        {collapsed ? (
          <span className="rule-double font-doc text-lg font-semibold leading-6 text-ink" aria-label="Procurement, Acme Corp">
            P
          </span>
        ) : (
          <div className="min-w-0 leading-tight">
            <p className="rule-double inline-block pb-0.5 text-[15px] font-semibold tracking-[-0.01em] text-ink">Procurement</p>
            <p className="mt-1 truncate text-caption text-ink-3">Acme Corp</p>
          </div>
        )}
      </div>

      <nav aria-label="Main" className="flex-1 space-y-px overflow-y-auto px-2 py-3 scrollbar-thin">
        {items.map((item) => (
          <Link
            key={item.to}
            to={item.to}
            onClick={onCloseMobile}
            aria-current={item.to === activeTo ? "page" : undefined}
            className={cn(
              "relative flex h-9 items-center gap-2.5 rounded px-2.5 text-sm transition-colors duration-1 lg:h-8 lg:text-13",
              item.to === activeTo
                ? "font-medium text-ink before:absolute before:-left-2 before:top-1.5 before:bottom-1.5 before:w-0.5 before:bg-accent lg:before:top-1 lg:before:bottom-1"
                : "text-ink-2 hover:bg-sheet-sunk hover:text-ink",
              collapsed && "justify-center px-2",
            )}
            aria-label={collapsed ? item.label : undefined}
            title={collapsed ? item.label : undefined}
          >
            <item.icon className={cn("size-4 shrink-0", item.to === activeTo ? "text-accent" : "text-ink-3")} strokeWidth={1.75} aria-hidden="true" />
            {!collapsed && <span className="truncate">{item.label}</span>}
          </Link>
        ))}
      </nav>

      <div className="border-t border-rule p-2">
        <div className={cn("flex items-center gap-2.5 rounded px-2 py-1.5", collapsed && "justify-center")}>
          <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-sheet text-caption font-semibold text-ink-2 ring-1 ring-rule-mid" aria-hidden="true">
            {initials(user.email)}
          </div>
          {!collapsed && (
            <NavLink to="/app/account" onClick={onCloseMobile} title="Account settings" className="min-w-0 flex-1 rounded leading-tight hover:underline">
              <p className="truncate text-caption font-medium text-ink">{user.email}</p>
              <p className="text-caption text-ink-3">{ROLE_LABELS[user.role]}</p>
            </NavLink>
          )}
          {!collapsed && (
            <button
              onClick={logout}
              aria-label="Sign out"
              title="Sign out"
              className="rounded p-1.5 text-ink-2 hover:bg-sheet-sunk hover:text-ink"
            >
              <LogOut className="size-4" strokeWidth={1.75} />
            </button>
          )}
        </div>
        <button
          onClick={onToggleCollapse}
          className="mt-1 hidden h-7 w-full items-center justify-center rounded text-ink-3 hover:bg-sheet-sunk hover:text-ink lg:flex"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <ChevronsLeft className={cn("size-4 transition-transform duration-2", collapsed && "rotate-180")} strokeWidth={1.75} aria-hidden="true" />
        </button>
      </div>
    </div>
  );

  return (
    <>
      <aside className={cn("hidden shrink-0 transition-[width] duration-2 ease-out lg:block", collapsed ? "w-14" : "w-56")}>
        {content}
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-ink/35 animate-fade-in" onClick={onCloseMobile} aria-hidden="true" />
          <div role="dialog" aria-modal="true" aria-label="Navigation" className="absolute left-0 top-0 h-full w-64 animate-slide-in-right shadow-popover">
            {content}
          </div>
        </div>
      )}
    </>
  );
}
