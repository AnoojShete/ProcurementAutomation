import { NavLink } from "react-router-dom";
import { Boxes, ChevronsLeft, LogOut } from "lucide-react";
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
    <div className="flex h-full flex-col bg-brand-900 text-brand-50">
      <div className={cn("flex items-center gap-2.5 px-4 py-5", collapsed && "justify-center px-2")}>
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-800">
          <Boxes className="size-[18px]" />
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-white">Procurement IQ</p>
            <p className="truncate text-[11px] text-brand-300">Acme Corp Workspace</p>
          </div>
        )}
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-2 scrollbar-thin">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onCloseMobile}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors",
                isActive ? "bg-brand-700 text-white" : "text-brand-200 hover:bg-brand-800 hover:text-white",
                collapsed && "justify-center px-2",
              )
            }
            title={collapsed ? item.label : undefined}
          >
            <item.icon className="size-[18px] shrink-0" />
            {!collapsed && <span className="truncate">{item.label}</span>}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-brand-800 p-3">
        <div className={cn("flex items-center gap-2.5", collapsed && "justify-center")}>
          <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-700 text-xs font-semibold text-white">
            {initials(user.email)}
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-white">{user.email}</p>
              <p className="text-[11px] text-brand-300">{ROLE_LABELS[user.role]}</p>
            </div>
          )}
          <button
            onClick={logout}
            aria-label="Sign out"
            title="Sign out"
            className="rounded-md p-1.5 text-brand-300 hover:bg-brand-800 hover:text-white"
          >
            <LogOut className="size-4" />
          </button>
        </div>
        <button
          onClick={onToggleCollapse}
          className="mt-2 hidden w-full items-center justify-center rounded-md py-1.5 text-brand-300 hover:bg-brand-800 hover:text-white lg:flex"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <ChevronsLeft className={cn("size-4 transition-transform", collapsed && "rotate-180")} />
        </button>
      </div>
    </div>
  );

  return (
    <>
      <aside className={cn("hidden shrink-0 transition-[width] duration-200 lg:block", collapsed ? "w-16" : "w-60")}>
        {content}
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/40" onClick={onCloseMobile} aria-hidden="true" />
          <div className="absolute left-0 top-0 h-full w-64 animate-slide-in-right shadow-popover">{content}</div>
        </div>
      )}
    </>
  );
}
