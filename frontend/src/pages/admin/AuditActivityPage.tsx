import { useMemo } from "react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { requestsApi } from "@/api/requests";
import { contractsApi } from "@/api/contracts";
import { notificationsApi } from "@/api/notifications";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Timeline, type TimelineEvent } from "@/components/ui/Timeline";
import { ErrorState } from "@/components/ui/ErrorState";
import { InlineInfo } from "@/components/ui/ErrorState";
import { formatDateTime } from "@/lib/format";

export function AuditActivityPage() {
  usePageHeader("Audit & Activity");
  const { data: requests, loading, error, reload } = useApi(() => requestsApi.list(200), []);
  const { data: contracts } = useApi(() => contractsApi.list(200), []);
  const { data: notifications } = useApi(() => notificationsApi.log({ limit: 200 }), []);

  const events: TimelineEvent[] = useMemo(() => {
    const list: TimelineEvent[] = [];
    (requests ?? []).forEach((r) => {
      if (r.created_at) list.push({ key: `${r.id}-created`, title: `Request created — ${r.request_type} (${r.department})`, timestamp: r.created_at, description: r.requested_by ?? undefined });
      (r.approval_history ?? []).forEach((h) =>
        list.push({
          key: h.id,
          title: `Request ${h.decision} by ${h.decided_by}`,
          timestamp: h.decided_at ?? undefined,
          tone: h.decision === "approved" ? "success" : "danger",
        }),
      );
    });
    (contracts ?? []).forEach((c) => {
      if (c.generated_at) list.push({ key: `${c.id}-gen`, title: `Contract generated (${c.template_used})`, timestamp: c.generated_at });
      if (c.signed_at) list.push({ key: `${c.id}-signed`, title: "Contract signed", timestamp: c.signed_at, tone: "success" });
    });
    (notifications ?? []).forEach((n) =>
      list.push({
        key: n.id,
        title: `Notification: ${n.event_type}`,
        timestamp: n.sent_at ?? n.created_at ?? undefined,
        description: `To ${n.recipient}`,
        tone: n.status === "failed" ? "danger" : undefined,
      }),
    );
    return list
      .filter((e) => e.timestamp)
      .sort((a, b) => (b.timestamp as string).localeCompare(a.timestamp as string))
      .slice(0, 100)
      .map((e) => ({ ...e, timestamp: formatDateTime(e.timestamp as string) }));
  }, [requests, contracts, notifications]);

  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-4">
      <InlineInfo message="Composed from each entity's own history fields and the notification log — there is no separate audit-log API in the current backend." />
      <Card>
        <CardHeader title="Platform Activity" subtitle="Most recent 100 events across requests, contracts, and notifications" />
        <CardBody>{loading ? <p className="text-sm text-slate-400">Loading…</p> : <Timeline events={events} />}</CardBody>
      </Card>
    </div>
  );
}
