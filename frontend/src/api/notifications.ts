import { api } from "./client";
import type { FeedEntry, NotificationLogEntry } from "@/types/api";

export interface NotificationTemplateSummary {
  name: string;
  /** The event that sends it. */
  event: string;
  /** Who it goes to. */
  recipient: string;
  description: string;
  subject: string;
  extra_recipients: string[];
  enabled: boolean;
  /** Created in the Control Panel (no built-in file). */
  is_custom: boolean;
  /** A built-in whose text was changed in the Control Panel. */
  customised: boolean;
  updated_by: string | null;
  updated_at: string | null;
}

export interface NotificationTemplate extends NotificationTemplateSummary {
  body: string;
  default: { subject: string; body: string } | null;
  placeholders: string[];
  /** True for built-ins: only these placeholders can be used. */
  placeholders_fixed: boolean;
}

export interface TemplateInput {
  subject: string;
  body: string;
  description?: string;
  extra_recipients: string[];
  enabled: boolean;
}

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

  // Templates (admin): edit the built-in emails or add new ones.
  templates: () => api.get<NotificationTemplateSummary[]>("/notifications/templates"),
  template: (name: string) => api.get<NotificationTemplate>(`/notifications/templates/${encodeURIComponent(name)}`),
  createTemplate: (data: TemplateInput & { name: string }) => api.post<NotificationTemplate>("/notifications/templates", data),
  updateTemplate: (name: string, data: TemplateInput) =>
    api.request<NotificationTemplate>(`/notifications/templates/${encodeURIComponent(name)}`, "PUT", data),
  /** Restores a built-in's default text, or deletes a custom template. */
  resetTemplate: (name: string) =>
    api.request<NotificationTemplate | { name: string; deleted: boolean }>(`/notifications/templates/${encodeURIComponent(name)}`, "DELETE"),
  previewTemplate: (name: string, subject: string, body: string) =>
    api.post<{ subject: string; body: string }>(`/notifications/templates/${encodeURIComponent(name)}/preview`, { subject, body }),
};
