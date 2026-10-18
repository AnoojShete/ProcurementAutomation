import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft, Bell, HelpCircle, Menu, Search } from "lucide-react";
import { useUnreadNotifications } from "@/hooks/useUnreadNotifications";
import { SYSTEM_SECTIONS } from "@/lib/roleNav";

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
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [helpOpen, setHelpOpen] = useState(false);
  // Every page except the dashboard gets a back arrow: browser-style back
  // when there's in-app history, otherwise up one level (a link opened in a
  // new tab still has somewhere sensible to go).
  const isHome = pathname.replace(/\/+$/, "") === "/app";
  const goBack = () => {
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0;
    const path = pathname.replace(/\/+$/, "");
    if (idx > 0) navigate(-1);
    else if (SYSTEM_SECTIONS.some((s) => s.to === path)) navigate("/app/system");
    else navigate(path.split("/").slice(0, -1).join("/") || "/app");
  };
  const { unread } = useUnreadNotifications();

  return (
    <header className="flex h-14 shrink-0 items-center gap-1.5 border-b border-rule bg-sheet px-3 sm:gap-2 sm:px-5">
      <button
        onClick={onOpenMobileNav}
        className="rounded p-2 text-ink-2 hover:bg-sheet-sunk hover:text-ink lg:hidden"
        aria-label="Open navigation"
      >
        <Menu className="size-5" />
      </button>

      {!isHome && (
        <button onClick={goBack} className="rounded p-2 text-ink-2 hover:bg-sheet-sunk hover:text-ink" aria-label="Go back" title="Back">
          <ArrowLeft className="size-[18px]" strokeWidth={1.75} />
        </button>
      )}

      <nav aria-label="Breadcrumb" className="flex min-w-0 flex-1 items-baseline gap-1.5">
        {breadcrumb && (
          <>
            <span className="hidden shrink-0 text-sm text-ink-3 sm:inline">{breadcrumb}</span>
            <span className="hidden text-rule-strong sm:inline" aria-hidden="true">/</span>
          </>
        )}
        <h1 className="truncate text-heading font-semibold text-ink">{title}</h1>
      </nav>

      <button
        onClick={onOpenSearch}
        className="hidden h-9 w-56 items-center gap-2 rounded border border-rule-strong bg-sheet px-2.5 text-13 text-ink-3 transition-colors duration-1 hover:border-ink-3 hover:text-ink-2 md:flex"
      >
        <Search className="size-3.5" aria-hidden="true" />
        <span className="flex-1 text-left">Search</span>
        <kbd className="rounded-sm border border-rule bg-paper px-1 font-sans text-caption text-ink-3">⌘K</kbd>
      </button>
      <button onClick={onOpenSearch} className="rounded p-2 text-ink-2 hover:bg-sheet-sunk hover:text-ink md:hidden" aria-label="Search">
        <Search className="size-5" />
      </button>

      <div className="relative">
        <button
          onClick={() => setHelpOpen((v) => !v)}
          className="rounded p-2 text-ink-2 hover:bg-sheet-sunk hover:text-ink"
          aria-label="Help"
          aria-expanded={helpOpen}
        >
          <HelpCircle className="size-[18px]" strokeWidth={1.75} />
        </button>
        {helpOpen && (
          <div className="absolute right-0 top-full z-20 mt-2 w-72 rounded-xl border border-rule bg-sheet p-4 text-sm shadow-popover animate-slide-up">
            <p className="font-medium text-ink">Need a hand?</p>
            <p className="mt-1 text-13 text-ink-2">Press ⌘K to search, or ask the assistant (bottom right).</p>
            <Link to="/app" onClick={() => setHelpOpen(false)} className="mt-2 inline-block text-13 font-medium text-accent hover:underline">
              Back to dashboard
            </Link>
          </div>
        )}
      </div>

      <Link
        to="/app/notifications"
        className="relative rounded p-2 text-ink-2 hover:bg-sheet-sunk hover:text-ink"
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"}
      >
        <Bell className="size-[18px]" strokeWidth={1.75} />
        {unread > 0 && (
          <span className="absolute right-0.5 top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger-500 px-1 text-caption font-semibold leading-none text-white ring-2 ring-sheet" aria-hidden="true">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </Link>
    </header>
  );
}
