import { useMemo } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Clock, FilePlus2, PackageCheck } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useApi } from "@/hooks/useApi";
import { usePageHeader } from "@/hooks/usePageTitle";
import { requestsApi } from "@/api/requests";
import { documentsApi } from "@/api/documents";
import { Greeting } from "@/components/dashboard/Greeting";
import { MetricCard } from "@/components/ui/MetricCard";
import { AttentionCard, type AttentionItem } from "@/components/dashboard/AttentionCard";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { StatusBadge } from "@/components/ui/Badge";
import { Timeline, type TimelineEvent } from "@/components/ui/Timeline";
import { Button } from "@/components/ui/Button";
import { SkeletonCard } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { formatCurrency, formatDate, formatDateTime } from "@/lib/format";
import type { PurchaseRequest } from "@/types/api";
import { useNavigate } from "react-router-dom";

export function RequesterDashboard() {
  const { user } = useAuth();
  usePageHeader("Dashboard");
  const navigate = useNavigate();
  const { data: allRequests, loading, error, reload } = useApi(() => requestsApi.list(200), []);
  const { data: reviewQueue } = useApi(() => documentsApi.reviewQueue(50), []);

  const myRequests = useMemo(
    () => (allRequests ?? []).filter((r) => r.requested_by === user?.email),
    [allRequests, user],
  );
  const myReviewDocs = useMemo(
    () => (reviewQueue ?? []).filter((d) => d.uploaded_by === user?.email),
    [reviewQueue, user],
  );

  const kpis = useMemo(() => {
    const awaitingApproval = myRequests.filter((r) => r.status === "pending_approval").length;
    const approved = myRequests.filter((r) => r.status === "approved").length;
    const fulfilled = myRequests.filter((r) => r.status === "fulfilled").length;
    const rejected = myRequests.filter((r) => r.status === "rejected").length;
    const open = myRequests.length - fulfilled - rejected;
    return { open, awaitingApproval, approved, fulfilled };
  }, [myRequests]);

  const attentionItems: AttentionItem[] = useMemo(() => {
    const items: AttentionItem[] = [];
    if (myReviewDocs.length > 0) {
      items.push({
        key: "docs-review",
        message: (
          <>
            <strong>{myReviewDocs.length}</strong> uploaded document{myReviewDocs.length > 1 ? "s" : ""} need
            {myReviewDocs.length > 1 ? "" : "s"} a correction before processing can finish.
          </>
        ),
        cta: "Review documents",
        to: "/app/documents",
      });
    }
    if (kpis.awaitingApproval > 0) {
      items.push({
        key: "open-requests",
        message: (
          <>
            <strong>{kpis.awaitingApproval}</strong> request{kpis.awaitingApproval > 1 ? "s are" : " is"} still awaiting approval.
          </>
        ),
        cta: "Track requests",
        to: "/app/requests",
      });
    }
    return items;
  }, [myReviewDocs, kpis]);

  const recentRequests = [...myRequests]
    .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""))
    .slice(0, 8);

  const activity: TimelineEvent[] = useMemo(() => {
    const events: TimelineEvent[] = [];
    myRequests
      .slice(0, 6)
      .forEach((r) => {
        events.push({
          key: `${r.id}-created`,
          title: `Request submitted — ${r.request_type ?? "purchase"}`,
          timestamp: formatDateTime(r.created_at),
          description: `${formatCurrency(r.amount, r.currency ?? "INR")} · ${r.department ?? ""}`,
        });
        (r.approval_history ?? []).forEach((h) => {
          events.push({
            key: h.id,
            title: `${h.decision === "approved" ? "Approved" : "Rejected"} by ${h.decided_by}`,
            timestamp: formatDateTime(h.decided_at),
            tone: h.decision === "approved" ? "success" : "danger",
          });
        });
      });
    return events.sort((a, b) => (b.timestamp ?? "").localeCompare(a.timestamp ?? "")).slice(0, 8);
  }, [myRequests]);

  const columns: Column<PurchaseRequest>[] = [
    { key: "id", header: "Request", render: (r) => <span className="font-mono text-xs">{r.id.slice(0, 8)}</span> },
    { key: "type", header: "Description", render: (r) => <span className="capitalize">{r.request_type ?? "—"}</span> },
    { key: "amount", header: "Amount", render: (r) => formatCurrency(r.amount, r.currency ?? "INR"), sortValue: (r) => r.amount ?? 0 },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "submitted", header: "Submitted", render: (r) => formatDate(r.created_at), sortValue: (r) => r.created_at ?? "" },
    {
      key: "next",
      header: "Next Action",
      render: (r) =>
        r.status === "pending_approval" ? (
          <span className="text-slate-500">Awaiting {r.approval_chain?.[r.current_approver_index] ?? "approval"}</span>
        ) : r.status === "approved" ? (
          <span className="text-slate-500">Awaiting contract</span>
        ) : (
          <span className="text-slate-400">—</span>
        ),
    },
  ];

  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <Greeting
          name={user?.email.split("@")[0] ?? "there"}
          subtitle="Here's what's happening with your procurement requests."
        />
        <Button icon={<FilePlus2 className="size-4" />} onClick={() => navigate("/app/requests/new")}>
          New Purchase Request
        </Button>
      </div>

      {loading ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <MetricCard label="Open Requests" value={kpis.open} icon={FilePlus2} tone="brand" />
          <MetricCard label="Awaiting Approval" value={kpis.awaitingApproval} icon={Clock} tone="warning" />
          <MetricCard label="Approved" value={kpis.approved} icon={CheckCircle2} tone="success" />
          <MetricCard label="Fulfilled" value={kpis.fulfilled} icon={PackageCheck} tone="brand" />
        </div>
      )}

      <AttentionCard items={attentionItems} />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader title="Recent Requests" subtitle="Your most recently submitted purchase requests" />
          <CardBody>
            <DataTable
              columns={columns}
              rows={recentRequests}
              rowKey={(r) => r.id}
              loading={loading}
              onRowClick={(r) => navigate(`/app/requests/${r.id}`)}
              emptyTitle="No requests yet"
              emptyDescription="Create your first purchase request to get started."
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Your Procurement Activity" subtitle="Recent updates across your requests" />
          <CardBody>
            <Timeline events={activity} />
            <Link to="/app/requests" className="mt-4 inline-block text-sm font-medium text-brand-700 hover:underline">
              View all requests →
            </Link>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
