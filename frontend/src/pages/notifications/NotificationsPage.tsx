import { useMemo, useState } from "react";
import { Bell, FileText, ScrollText, ShieldAlert, Boxes, Files } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { notificationsApi } from "@/api/notifications";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { SkeletonTable } from "@/components/ui/Skeleton";
import { formatDateTime, titleCase } from "@/lib/format";

const CATEGORY_ICON: Record<string, typeof Bell> = {
  approval: ScrollText,
  contract: FileText,
  risk: ShieldAlert,
  inventory: Boxes,
  document: Files,
};

function categoryFromEventType(eventType: string): string {
  const key = eventType.split(".")[0];
  return CATEGORY_ICON[key] ? key : "system";
}

export function NotificationsPage() {
  usePageHeader("Notifications");
  const { data: notifications, loading, error, reload } = useApi(() => notificationsApi.log({ limit: 200 }), []);
  const [priorityFilter, setPriorityFilter] = useState<string>("all");

  const filtered = useMemo(() => {
    if (priorityFilter === "all") return notifications ?? [];
    return (notifications ?? []).filter((n) => n.priority === priorityFilter);
  }, [notifications, priorityFilter]);

  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        {["all", "urgent", "digest"].map((p) => (
          <button
            key={p}
            onClick={() => setPriorityFilter(p)}
            className={`rounded-full border px-3 py-1.5 text-sm font-medium capitalize transition-colors ${
              priorityFilter === p ? "border-brand-600 bg-brand-50 text-brand-700" : "border-surface-border text-slate-600 hover:border-slate-300"
            }`}
          >
            {p}
          </button>
        ))}
      </div>

      <Card>
        <CardBody>
          {loading ? (
            <SkeletonTable cols={4} />
          ) : filtered.length === 0 ? (
            <EmptyState icon={Bell} title="No notifications" description="Notifications about approvals, contracts, risk, and documents will appear here." />
          ) : (
            <ul className="flex flex-col divide-y divide-surface-border">
              {filtered.map((n) => {
                const category = categoryFromEventType(n.event_type);
                const Icon = CATEGORY_ICON[category] ?? Bell;
                return (
                  <li key={n.id} className="flex items-start gap-3 py-3">
                    <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-slate-500">
                      <Icon className="size-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-medium text-slate-800">{n.subject ?? titleCase(n.event_type)}</p>
                        {n.priority === "urgent" && <Badge tone="danger">Urgent</Badge>}
                        <Badge tone={n.status === "sent" ? "success" : n.status === "failed" ? "danger" : "neutral"}>{n.status}</Badge>
                      </div>
                      <p className="mt-0.5 text-xs text-slate-500">
                        To {n.recipient} · via {n.channel} · {formatDateTime(n.sent_at ?? n.created_at)}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
