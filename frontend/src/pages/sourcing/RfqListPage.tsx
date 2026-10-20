import { useNavigate } from "react-router-dom";
import { sourcingApi } from "@/api/sourcing";
import { vendorsApi } from "@/api/vendors";
import { NewRfq } from "@/components/approvals/SourcingActions";
import { StatusDot } from "@/components/ui/Badge";
import { Section } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { ErrorState } from "@/components/ui/ErrorState";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { usePageHeader } from "@/hooks/usePageTitle";
import { formatDateTime } from "@/lib/format";
import type { RfqStatus, RfqSummary } from "@/types/api";

export const RFQ_STATUS: Record<RfqStatus, { tone: "warning" | "brand" | "success" | "neutral"; label: string }> = {
  open: { tone: "warning", label: "Collecting quotes" },
  closed: { tone: "brand", label: "Ready to decide" },
  awarded: { tone: "success", label: "Awarded" },
  cancelled: { tone: "neutral", label: "Cancelled" },
};

/** Phase 3b: RFQ events. Approvers follow them; finance and admin run them. */
export function RfqListPage() {
  usePageHeader("Sourcing");
  const navigate = useNavigate();
  const { user } = useAuth();
  const canRun = user?.role === "finance" || user?.role === "admin";
  const { data: rfqs, loading, error, reload } = useApi(() => sourcingApi.list(), []);
  const { data: vendors } = useApi(() => (canRun ? vendorsApi.list(200) : Promise.resolve({ data: [] })), [canRun]);

  const columns: Column<RfqSummary>[] = [
    { key: "ref", header: "Reference", render: (r) => <span className="font-mono text-13">{r.reference}</span>, sortValue: (r) => r.reference },
    { key: "title", header: "Title", render: (r) => <span className="text-ink">{r.title}</span>, sortValue: (r) => r.title.toLowerCase() },
    { key: "dept", header: "Department", render: (r) => r.department, hideOnMobile: true },
    { key: "quotes", header: "Quotes", render: (r) => `${r.responded ?? 0} of ${r.invited ?? 0}${r.round > 1 ? ` · round ${r.round}` : ""}` },
    { key: "deadline", header: "Deadline", render: (r) => formatDateTime(r.deadline), sortValue: (r) => r.deadline, hideOnMobile: true },
    { key: "status", header: "Status", render: (r) => <StatusDot tone={RFQ_STATUS[r.status].tone}>{RFQ_STATUS[r.status].label}</StatusDot>, sortValue: (r) => r.status },
  ];

  if (error) return <ErrorState message={error} onRetry={reload} />;
  return (
    <div className="flex flex-col gap-6">
      <Section title="Requests for quotation" subtitle="Larger purchases are compared across vendors on price, lead time, warranty, support, risk and delivery record.">
        <DataTable columns={columns} rows={rfqs ?? []} rowKey={(r) => r.id} loading={loading && !rfqs}
          emptyTitle="No RFQs yet" emptyDescription={canRun ? "Issue one below." : "Finance issues RFQs for larger purchases."}
          onRowClick={(r) => navigate(`/app/sourcing/${r.id}`)} />
      </Section>
      {canRun && <NewRfq vendors={vendors ?? []} />}
    </div>
  );
}
