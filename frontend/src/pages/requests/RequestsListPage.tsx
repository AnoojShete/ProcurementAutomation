import { useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { FilePlus2 } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { requestsApi } from "@/api/requests";
import { Card, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { Tabs } from "@/components/ui/Tabs";
import { PersonName } from "@/components/people/PersonName";
import { FilterChip } from "@/components/ui/FilterChip";
import { formatCurrency, formatDate, titleCase } from "@/lib/format";
import type { PurchaseRequest } from "@/types/api";

// "open" = still moving: not received, invoiced, rejected or cancelled.
const CLOSED = ["fulfilled", "partially_invoiced", "invoice_received", "rejected", "cancelled"];

export type RequestScope = "all" | "mine" | "approved";

export function RequestsListPage() {
  usePageHeader("My Requests", "Requests");
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data: requests, loading, error, reload } = useApi(() => requestsApi.list(200), []);
  // Filters live in the URL so dashboard figures can link straight to them:
  // ?scope=mine&status=pending_approval,approved&approved_by=me&vendor=<id>&backordered=1
  const [params, setParams] = useSearchParams();
  const rawScope = params.get("scope");
  const approvedByMe = params.get("approved_by") === "me";
  const defaultScope: RequestScope = user?.role === "requester" ? "mine" : approvedByMe ? "approved" : "all";
  const scope: RequestScope = (rawScope as RequestScope) ?? defaultScope;
  const statuses = params.get("status")?.split(",").filter(Boolean) ?? [];
  const vendorId = params.get("vendor");
  const backordered = params.get("backordered") === "1";
  const filtered = statuses.length > 0 || (approvedByMe && scope !== "approved") || !!vendorId || backordered;

  const setScope = (k: RequestScope) => {
    const next = new URLSearchParams(params);
    next.set("scope", k);
    if (k === "approved") {
      next.delete("approved_by");
    }
    setParams(next, { replace: true });
  };
  const clearFilters = () => setParams(params.get("scope") ? { scope } : {}, { replace: true });

  const rows = useMemo(() => {
    const me = user?.email.toLowerCase();
    return (requests ?? []).filter((r) => {
      if (scope === "mine" && r.requested_by?.toLowerCase() !== me) return false;
      if (scope === "approved") {
        const approvedByMe = r.approval_history?.some(
          (h) => h.decision === "approved" && h.decided_by?.toLowerCase() === me
        );
        if (!approvedByMe) {
          if (user?.role === "approver" && r.approval_chain?.includes("dept_manager")) {
            const deptIdx = r.approval_chain.indexOf("dept_manager");
            if (r.current_approver_index <= deptIdx) return false;
          } else {
            return false;
          }
        }
      }
      if (statuses.length) {
        const ok = statuses.some((st) => (st === "open" ? !CLOSED.includes(r.status ?? "") : r.status === st));
        if (!ok) return false;
      }
      if (approvedByMe && !r.approval_history?.some((h) => h.decision === "approved" && h.decided_by?.toLowerCase() === me)) return false;
      if (vendorId && r.vendor_id !== vendorId) return false;
      if (backordered && !(r.is_backordered && r.status !== "rejected")) return false;
      return true;
    });
  }, [requests, scope, user, statuses, approvedByMe, vendorId, backordered]);

  const filterLabel = [
    statuses.map((st) => (st === "open" ? "Open" : titleCase(st))).join(" or "),
    approvedByMe && scope !== "approved" && "approved by you",
    vendorId && "this vendor",
    backordered && "backordered",
  ]
    .filter(Boolean)
    .join(" · ");

  const columns: Column<PurchaseRequest>[] = [
    { key: "id", header: "Request", render: (r) => <span className="font-mono text-xs">{r.id.slice(0, 8)}</span> },
    { key: "type", header: "Type", render: (r) => titleCase(r.request_type) },
    { key: "requester", header: "Requester", render: (r) => <PersonName email={r.requested_by} />, hideOnMobile: scope !== "all" },
    { key: "dept", header: "Department", render: (r) => r.department ?? "—" },
    { key: "amount", header: "Amount", render: (r) => formatCurrency(r.amount, r.currency ?? "INR"), sortValue: (r) => r.amount ?? 0 },
    { key: "tier", header: "Tier", render: (r) => <span className="text-ink-2">{titleCase(r.spend_tier)}</span> },
    {
      key: "status",
      header: "Status",
      render: (r) => {
        if (r.status === "pending_approval") {
          const chain = r.approval_chain || [];
          const currentLevel = chain[r.current_approver_index];
          const levelName = currentLevel === "finance_head" ? "Finance Head" : currentLevel === "dept_manager" ? "Dept Manager" : currentLevel ? titleCase(currentLevel) : "Approver";
          return (
            <span className="inline-flex items-center gap-1.5">
              <StatusBadge status="pending_approval" />
              <span className="text-xs text-amber-700 font-medium">({levelName})</span>
            </span>
          );
        }
        return <StatusBadge status={r.status} />;
      },
    },
    { key: "created", header: "Submitted", render: (r) => formatDate(r.created_at), sortValue: (r) => r.created_at ?? "" },
  ];

  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {user?.role !== "requester" ? (
          <Tabs
            tabs={[
              { key: "all", label: "All Requests" },
              { key: "mine", label: "Created by me" },
              { key: "approved", label: "Approved by me" },
            ]}
            active={scope}
            onChange={(k) => setScope(k as RequestScope)}
          />
        ) : (
          <div />
        )}
        {filtered && (
          <span className="mr-auto">
            <FilterChip label={filterLabel} onClear={clearFilters} />
          </span>
        )}
        <Button variant="primary" onClick={() => navigate("/app/requests/new")} className="ml-auto">
          <FilePlus2 className="size-4" />
          <span>New Request</span>
        </Button>
      </div>

      <Card>
        <CardBody>
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(r) => r.id}
            loading={loading}
            onRowClick={(r) => navigate(`/app/requests/${r.id}`)}
            emptyTitle={scope === "mine" ? "You haven't submitted any requests yet" : scope === "approved" ? "No requests approved by you yet" : "No requests found"}
          />
        </CardBody>
      </Card>
    </div>
  );
}
