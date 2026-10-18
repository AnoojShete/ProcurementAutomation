import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { notificationsApi } from "@/api/notifications";

interface UnreadContextValue {
  unread: number;
  /** Set straight from a read/read-all response (it returns the new count). */
  setUnread: (n: number) => void;
  refresh: () => void;
}

const UnreadContext = createContext<UnreadContextValue | null>(null);
const POLL_MS = 60_000;

/** The bell's count: unread important notifications, kept by the
 * notification-agent per account (so it survives reloads and new
 * sessions). Re-checked on every page change, on focus, and each minute. */
export function UnreadNotificationsProvider({ children }: { children: ReactNode }) {
  const [unread, setUnread] = useState(0);
  const { pathname } = useLocation();

  const refresh = useCallback(() => {
    notificationsApi
      .unreadCount()
      .then((r) => setUnread(r.data.unread))
      .catch(() => undefined); // keep the last known count
  }, []);

  useEffect(refresh, [pathname, refresh]);
  useEffect(() => {
    const id = setInterval(refresh, POLL_MS);
    window.addEventListener("focus", refresh);
    return () => {
      clearInterval(id);
      window.removeEventListener("focus", refresh);
    };
  }, [refresh]);

  return <UnreadContext.Provider value={{ unread, setUnread, refresh }}>{children}</UnreadContext.Provider>;
}

export function useUnreadNotifications(): UnreadContextValue {
  const ctx = useContext(UnreadContext);
  if (!ctx) throw new Error("useUnreadNotifications must be used within UnreadNotificationsProvider");
  return ctx;
}
