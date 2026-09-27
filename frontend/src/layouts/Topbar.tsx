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
    <header className="flex h-12 shrink-0 items-center gap-2 border-b border-surface-border bg-white px-4">
      <button
        onClick={onOpenMobileNav}
        className="rounded-md p-1.5 text-slate-500 hover:bg-surface-muted lg:hidden"
        aria-label="Open navigation"
      >
        <Menu className="size-5" />
      </button>

      <nav aria-label="Breadcrumb" className="flex min-w-0 flex-1 items-center gap-1.5 text-sm">
        {breadcrumb && (
          <>
            <span className="shrink-0 text-slate-500">{breadcrumb}</span>
            <span className="text-slate-300" aria-hidden="true">/</span>
          </>
        )}
        <h1 className="truncate font-semibold text-slate-900">{title}</h1>
      </nav>

      <button
        onClick={onOpenSearch}
        className="hidden h-8 w-56 items-center gap-2 rounded-md border border-surface-border bg-surface-subtle px-2.5 text-13 text-slate-500 hover:border-slate-400 md:flex"
      >
        <Search className="size-3.5" />
        <span className="flex-1 text-left">Search</span>
        <kbd className="rounded border border-surface-border bg-white px-1 font-sans text-[11px] text-slate-500">⌘K</kbd>
      </button>
      <button onClick={onOpenSearch} className="rounded-md p-1.5 text-slate-500 hover:bg-surface-muted md:hidden" aria-label="Search">
        <Search className="size-5" />
      </button>

      <div className="relative">
        <button
          onClick={() => setHelpOpen((v) => !v)}
          className="rounded-md p-1.5 text-slate-500 hover:bg-surface-muted"
          aria-label="Help"
          aria-expanded={helpOpen}
        >
          <HelpCircle className="size-[18px]" strokeWidth={1.75} />
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
        <Bell className="size-[18px]" strokeWidth={1.75} />
        {urgentCount > 0 && (
          <span className="absolute right-0.5 top-0.5 flex size-4 items-center justify-center rounded-full bg-danger-500 text-[10px] font-semibold text-white ring-2 ring-white">
            {urgentCount > 9 ? "9+" : urgentCount}
          </span>
        )}
      </Link>
    </header>
  );
}
