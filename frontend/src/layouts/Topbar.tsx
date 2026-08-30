import { useState } from "react";
import { Link } from "react-router-dom";
import { Bell, HelpCircle, Menu, Search } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { notificationsApi } from "@/api/notifications";
import { useAuth } from "@/hooks/useAuth";

export function Topbar({
  title,
  breadcrumb,
  onOpenMobileNav,
  onOpenSearch,
}: {
  title: string;
  breadcrumb?: string;
  onOpenMobileNav: () => void;
  onOpenSearch: () => void;
}) {
  const { user } = useAuth();
  const [helpOpen, setHelpOpen] = useState(false);
  const { data: notifications } = useApi(
    () => notificationsApi.log({ recipient: user?.email, limit: 20 }),
    [user?.email],
  );
  // The backend tracks delivery status (sent/queued/failed), not a per-user
  // read flag — there's no "unread" concept to report, so the badge surfaces
  // urgent-priority notifications instead, a real field on the log entry.
  const urgentCount = notifications?.filter((n) => n.priority === "urgent").length ?? 0;

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-surface-border bg-white px-4">
      <button
        onClick={onOpenMobileNav}
        className="rounded-md p-1.5 text-slate-500 hover:bg-surface-muted lg:hidden"
        aria-label="Open navigation"
      >
        <Menu className="size-5" />
      </button>

      <div className="min-w-0 flex-1">
        {breadcrumb && <p className="text-xs text-slate-400">{breadcrumb}</p>}
        <h1 className="truncate text-base font-semibold text-slate-900">{title}</h1>
      </div>

      <button
        onClick={onOpenSearch}
        className="hidden items-center gap-2 rounded-lg border border-surface-border bg-surface-subtle px-3 py-1.5 text-sm text-slate-400 hover:border-slate-300 sm:flex"
      >
        <Search className="size-3.5" />
        <span>Search…</span>
        <kbd className="ml-4 rounded border border-surface-border bg-white px-1.5 py-0.5 text-[11px]">⌘K</kbd>
      </button>
      <button onClick={onOpenSearch} className="rounded-md p-1.5 text-slate-500 hover:bg-surface-muted sm:hidden" aria-label="Search">
        <Search className="size-5" />
      </button>

      <div className="relative">
        <button
          onClick={() => setHelpOpen((v) => !v)}
          className="rounded-md p-1.5 text-slate-500 hover:bg-surface-muted"
          aria-label="Help"
          aria-expanded={helpOpen}
        >
          <HelpCircle className="size-5" />
        </button>
        {helpOpen && (
          <div className="absolute right-0 top-full z-20 mt-2 w-64 rounded-lg border border-surface-border bg-white p-3 text-sm shadow-popover animate-slide-up">
            <p className="font-medium text-slate-800">Need a hand?</p>
            <p className="mt-1 text-slate-500">
              This is a demo environment covering the full procurement lifecycle — request, document intelligence,
              approval, contract, and vendor risk.
            </p>
            <Link to="/app" onClick={() => setHelpOpen(false)} className="mt-2 inline-block text-brand-700 hover:underline">
              Back to dashboard
            </Link>
          </div>
        )}
      </div>

      <Link
        to="/app/notifications"
        className="relative rounded-md p-1.5 text-slate-500 hover:bg-surface-muted"
        aria-label={urgentCount > 0 ? `Notifications, ${urgentCount} urgent` : "Notifications"}
      >
        <Bell className="size-5" />
        {urgentCount > 0 && (
          <span className="absolute right-1 top-1 flex size-4 items-center justify-center rounded-full bg-danger-500 text-[10px] font-semibold text-white">
            {urgentCount > 9 ? "9+" : urgentCount}
          </span>
        )}
      </Link>
    </header>
  );
}
