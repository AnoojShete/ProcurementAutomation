import { api } from "./client";
import type { NotificationLogEntry } from "@/types/api";

export const notificationsApi = {
  log: (params?: { recipient?: string; event_type?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.recipient) qs.set("recipient", params.recipient);
    if (params?.event_type) qs.set("event_type", params.event_type);
    qs.set("limit", String(params?.limit ?? 200));
    return api.get<NotificationLogEntry[]>(`/notifications/log?${qs.toString()}`);
  },
};
