import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { CommandPalette } from "@/components/CommandPalette";
import { PageHeaderProvider, usePageTitle } from "@/hooks/usePageTitle";
import { BotMessageSquare } from "lucide-react";
import { ChatDrawer } from "@/components/ui/ChatDrawer";
import { PeopleProvider } from "@/hooks/usePeople";
import { UnreadNotificationsProvider } from "@/hooks/useUnreadNotifications";

export function AppShell() {
  return (
    <PageHeaderProvider>
      <PeopleProvider>
        <UnreadNotificationsProvider>
          <AppShellInner />
        </UnreadNotificationsProvider>
      </PeopleProvider>
    </PageHeaderProvider>
  );
}

function AppShellInner() {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const { title, breadcrumb } = usePageTitle();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex h-screen overflow-hidden bg-paper relative">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <Sidebar
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((c) => !c)}
        mobileOpen={mobileNavOpen}
        onCloseMobile={() => setMobileNavOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar
          title={title}
          breadcrumb={breadcrumb}
          onOpenMobileNav={() => setMobileNavOpen(true)}
          onOpenSearch={() => setSearchOpen(true)}
        />
        {/* pb-24 reserves a gutter under the last row so the floating chat
            button (owned by the chatbot) never hides the end of a page. */}
        {/* Focusable so keyboard users can scroll pages that have no other
            focusable content; the skip link lands here too. */}
        <main
          id="main"
          tabIndex={0}
          aria-label="Page content"
          className="flex-1 overflow-y-auto focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent focus-visible:ring-offset-0"
        >
          <div className="max-w-[1200px] px-4 pb-24 pt-6 sm:px-6 lg:px-8 2xl:mx-auto">
            <Outlet />
          </div>
        </main>
      </div>
      <CommandPalette open={searchOpen} onClose={() => setSearchOpen(false)} />
      
      {/* Floating Chat Button */}
      <button
        onClick={() => setChatOpen(true)}
        className="fixed bottom-6 right-6 p-4 bg-blue-600 text-white rounded-full shadow-lg hover:bg-blue-700 transition-colors z-30"
        aria-label="Open AI Assistant"
      >
        <BotMessageSquare className="w-6 h-6" />
      </button>

      {/* The Chat Drawer */}
      <ChatDrawer open={chatOpen} onClose={() => setChatOpen(false)} />
    </div>
  );
}
