import { api } from "./client";
import type { FeedEntry, NotificationLogEntry } from "@/types/api";

export const notificationsApi = {
  /** The whole log (staff) or your own (everyone else): the history view. */
  log: (params?: { recipient?: string; event_type?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.recipient) qs.set("recipient", params.recipient);
    if (params?.event_type) qs.set("event_type", params.event_type);
    qs.set("limit", String(params?.limit ?? 200));
    return api.get<NotificationLogEntry[]>(`/notifications/log?${qs.toString()}`);
  },
  /** Your notifications with read state. "important" = what the bell counts. */
  feed: (scope: "important" | "all" = "important", limit = 100) =>
    api.get<FeedEntry[]>(`/notifications/feed?scope=${scope}&limit=${limit}`),
  unreadCount: () => api.get<{ unread: number }>("/notifications/unread-count"),
  markRead: (id: string) => api.post<{ marked: number; unread: number }>(`/notifications/${id}/read`),
  markAllRead: () => api.post<{ marked: number; unread: number }>("/notifications/read-all"),
};
