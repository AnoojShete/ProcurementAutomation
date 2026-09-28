import { NavLink } from "react-router-dom";
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
  if (!user) return null;
  const items = ROLE_NAV[user.role];

  const content = (
    <div className="flex h-full flex-col border-r border-surface-border bg-white">
      <div className={cn("flex h-12 items-center gap-2.5 border-b border-surface-border px-4", collapsed && "justify-center px-2")}>
        <div className="flex size-6 shrink-0 items-center justify-center rounded bg-slate-900 text-[11px] font-bold tracking-tight text-white">
          PI
        </div>
        {!collapsed && (
          <div className="min-w-0 leading-tight">
            <p className="truncate text-sm font-semibold text-slate-900">Procurement</p>
            <p className="truncate text-[11px] text-slate-500">Acme Corp</p>
          </div>
        )}
      </div>

      <nav className="flex-1 space-y-px overflow-y-auto px-2 py-3 scrollbar-thin">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onCloseMobile}
            className={({ isActive }) =>
              cn(
                "relative flex h-8 items-center gap-2.5 rounded-md px-2.5 text-13 transition-colors",
                isActive
                  ? "bg-surface-muted font-medium text-slate-900 before:absolute before:-left-2 before:top-1.5 before:h-5 before:w-[3px] before:rounded-r before:bg-brand-500"
                  : "text-slate-600 hover:bg-surface-subtle hover:text-slate-900",
                collapsed && "justify-center px-2",
              )
            }
            title={collapsed ? item.label : undefined}
          >
            <item.icon className="size-4 shrink-0 text-slate-500" strokeWidth={1.75} />
            {!collapsed && <span className="truncate">{item.label}</span>}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-surface-border p-2">
        <div className={cn("flex items-center gap-2.5 rounded-md px-2 py-1.5", collapsed && "justify-center")}>
          <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-surface-muted text-[11px] font-semibold text-slate-700 ring-1 ring-surface-border">
            {initials(user.email)}
          </div>
          {!collapsed && (
            <NavLink to="/app/account" onClick={onCloseMobile} title="Account settings" className="min-w-0 flex-1 rounded leading-tight hover:underline">
              <p className="truncate text-xs font-medium text-slate-900">{user.email}</p>
              <p className="text-[11px] text-slate-500">{ROLE_LABELS[user.role]}</p>
            </NavLink>
          )}
          {!collapsed && (
            <button
              onClick={logout}
              aria-label="Sign out"
              title="Sign out"
              className="rounded p-1 text-slate-500 hover:bg-surface-muted hover:text-slate-900"
            >
              <LogOut className="size-4" strokeWidth={1.75} />
            </button>
          )}
        </div>
        <button
          onClick={onToggleCollapse}
          className="mt-1 hidden h-7 w-full items-center justify-center rounded-md text-slate-500 hover:bg-surface-subtle hover:text-slate-900 lg:flex"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <ChevronsLeft className={cn("size-4 transition-transform", collapsed && "rotate-180")} strokeWidth={1.75} />
        </button>
      </div>
    </div>
  );

  return (
    <>
      <aside className={cn("hidden shrink-0 transition-[width] duration-200 lg:block", collapsed ? "w-14" : "w-56")}>
        {content}
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/40" onClick={onCloseMobile} aria-hidden="true" />
          <div className="absolute left-0 top-0 h-full w-60 animate-slide-in-right shadow-popover">{content}</div>
        </div>
      )}
    </>
  );
}
