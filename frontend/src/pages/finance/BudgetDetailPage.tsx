import { Link, useParams } from "react-router-dom";
import { budgetsApi } from "@/api/budgets";
import { BudgetEditActions } from "@/components/approvals/BudgetActions";
import { StatusDot } from "@/components/ui/Badge";
import { Section } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { DocketHeader, RefCopy } from "@/components/ui/DocketHeader";
import { ErrorState } from "@/components/ui/ErrorState";
import { LedgerStrip, MetricCard } from "@/components/ui/MetricCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { usePeople } from "@/hooks/usePeople";
import { usePageHeader } from "@/hooks/usePageTitle";
import { formatCurrency, formatDate, titleCase } from "@/lib/format";
import type { BudgetRequestRow } from "@/types/api";

const CATEGORY_LABELS: Record<string, string> = { hardware: "Hardware", software: "Software licences", saas: "SaaS", services: "IT services" };
const COUNTS: Record<BudgetRequestRow["counts_as"], { tone: "neutral" | "warning" | "success"; label: string }> = {
  "consumed/committed": { tone: "success", label: "Approved" },
  pending: { tone: "warning", label: "Awaiting approval" },
  released: { tone: "neutral", label: "Not counted" },
};

export function BudgetDetailPage() {
  const { id = "" } = useParams();
  const { user } = useAuth();
  const { nameFor } = usePeople();
  const { data: budget, loading, error, reload } = useApi(() => budgetsApi.get(id), [id]);
  usePageHeader(budget ? `${budget.department} · ${CATEGORY_LABELS[budget.category] ?? budget.category}` : "Budget", "Budgets");

  if (loading && !budget) return <Skeleton className="h-96" />;
  if (error || !budget) return <ErrorState message={error ?? "Budget not found."} onRetry={reload} />;

  const status = budget.status === "over" ? { tone: "danger" as const, label: "Over budget" }
    : budget.status === "warning" ? { tone: "warning" as const, label: "Near the limit" } : { tone: "success" as const, label: "Within budget" };

  const columns: Column<BudgetRequestRow>[] = [
    { key: "id", header: "Request", render: (r) => <Link to={`/app/requests/${r.id}`} className="font-mono text-13 text-accent hover:underline">PR-{r.id.slice(0, 8)}</Link> },
    { key: "type", header: "Type", render: (r) => titleCase(r.request_type ?? "—") },
    { key: "by", header: "Requested by", render: (r) => nameFor(r.requested_by), hideOnMobile: true },
    { key: "amount", header: "Amount", render: (r) => <span className="tabular">{formatCurrency(r.amount)}</span>, sortValue: (r) => r.amount },
    { key: "invoiced", header: "Invoiced", render: (r) => <span className="tabular">{formatCurrency(r.invoiced)}</span>, sortValue: (r) => r.invoiced, hideOnMobile: true },
    { key: "status", header: "Status", render: (r) => titleCase(r.status) },
    { key: "counts", header: "Counts as", render: (r) => <StatusDot tone={COUNTS[r.counts_as].tone}>{COUNTS[r.counts_as].label}</StatusDot> },
    { key: "created", header: "Created", render: (r) => (r.created_at ? formatDate(r.created_at) : "—"), sortValue: (r) => r.created_at ?? "", hideOnMobile: true },
  ];

  return (
    <div className="flex flex-col gap-6">
      <DocketHeader
        reference={<RefCopy prefix="BUD" id={budget.id} />}
        title={`${budget.department} · ${CATEGORY_LABELS[budget.category] ?? budget.category}`}
        status={<StatusDot tone={status.tone}>{status.label}</StatusDot>}
        meta={`${budget.period} ${budget.fiscal_year}${budget.owner_email ? ` · owner ${nameFor(budget.owner_email)}` : ""}`}
      />
      <LedgerStrip cols={5} label="Budget figures">
        <MetricCard label="Budget" value={formatCurrency(budget.amount_inr)} />
        <MetricCard label="Invoiced" value={formatCurrency(budget.consumed)} hint="consumed" />
        <MetricCard label="Approved, not invoiced" value={formatCurrency(budget.committed)} hint="committed" />
        <MetricCard label="Awaiting approval" value={formatCurrency(budget.pending)} hint="pending" />
        <MetricCard label="Left" value={formatCurrency(budget.left)} tone={budget.left < 0 ? "danger" : budget.status === "warning" ? "warning" : "neutral"} />
      </LedgerStrip>

      {(user?.role === "finance" || user?.role === "admin") && (
        <BudgetEditActions budget={budget} inUse={budget.requests.length > 0} onChanged={reload} />
      )}

      <Section title="Requests drawing on this budget" subtitle="Rejected, cancelled and split requests are listed but no longer count.">
        <DataTable columns={columns} rows={budget.requests} rowKey={(r) => r.id} emptyTitle="No requests yet" />
      </Section>
    </div>
  );
}
