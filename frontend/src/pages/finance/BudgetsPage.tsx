import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { budgetsApi } from "@/api/budgets";
import { BudgetPlanningActions } from "@/components/approvals/BudgetActions";
import { StatusDot } from "@/components/ui/Badge";
import { Section } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { ErrorState } from "@/components/ui/ErrorState";
import { LedgerStrip, MetricCard } from "@/components/ui/MetricCard";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { usePageHeader } from "@/hooks/usePageTitle";
import { formatCurrency } from "@/lib/format";
import type { Budget } from "@/types/api";

const CATEGORY_LABELS: Record<string, string> = { hardware: "Hardware", software: "Software licences", saas: "SaaS", services: "IT services" };
const STATUS: Record<Budget["status"], { tone: "success" | "warning" | "danger"; label: string }> = {
  within: { tone: "success", label: "Within" },
  warning: { tone: "warning", label: "Near the limit" },
  over: { tone: "danger", label: "Over" },
};

function UsedBar({ budget }: { budget: Budget }) {
  const actual = budget.amount_inr ? (budget.used / budget.amount_inr) * 100 : budget.used > 0 ? 100 : 0;
  const pct = Math.min(100, actual);
  const tone = budget.status === "over" ? "bg-danger-500" : budget.status === "warning" ? "bg-warning-500" : "bg-ink-3";
  return (
    <div className="flex min-w-32 items-center gap-2" title={`${Math.round(actual)}% used (consumed + committed + pending)`}>
      <div className="h-1.5 flex-1 rounded-full bg-sheet-sunk"><div className={`h-1.5 rounded-full ${tone}`} style={{ width: `${pct}%` }} /></div>
      <span className="w-10 text-right text-13 tabular text-ink-2">{Math.round(actual)}%</span>
    </div>
  );
}

export function BudgetsPage() {
  usePageHeader("Budgets");
  const navigate = useNavigate();
  const { user } = useAuth();
  const canEdit = user?.role === "finance" || user?.role === "admin";
  const { data: current, error: periodError } = useApi(() => budgetsApi.period(), []);
  const [scope, setScope] = useState<{ fiscal_year: string; period: string } | null>(null);
  useEffect(() => { if (current && !scope) setScope({ fiscal_year: current.fiscal_year, period: current.period }); }, [current, scope]);
  const { data: budgets, loading, error, reload } = useApi(
    () => (scope ? budgetsApi.list(scope) : Promise.resolve({ data: [] as Budget[] })), [scope?.fiscal_year, scope?.period]);

  const totals = useMemo(() => (budgets ?? []).reduce(
    (t, b) => ({ amount: t.amount + b.amount_inr, consumed: t.consumed + b.consumed, committed: t.committed + b.committed,
                 pending: t.pending + b.pending, left: t.left + b.left }),
    { amount: 0, consumed: 0, committed: 0, pending: 0, left: 0 }), [budgets]);

  const periods = current?.period_type === "annual" ? ["FY"] : ["Q1", "Q2", "Q3", "Q4"];
  const years = useMemo(() => {
    if (!current) return [];
    const first = Number(current.fiscal_year.slice(0, 4));
    return [first - 1, first, first + 1].map((y) => `${y}-${String((y + 1) % 100).padStart(2, "0")}`);
  }, [current]);

  const columns: Column<Budget>[] = [
    { key: "department", header: "Department", render: (b) => b.department, sortValue: (b) => b.department.toLowerCase() },
    { key: "category", header: "Category", render: (b) => CATEGORY_LABELS[b.category] ?? b.category, sortValue: (b) => b.category },
    { key: "amount", header: "Budget", render: (b) => <span className="tabular">{formatCurrency(b.amount_inr)}</span>, sortValue: (b) => b.amount_inr },
    { key: "used", header: "Used", render: (b) => <UsedBar budget={b} />, sortValue: (b) => b.used_pct ?? 0, hideOnMobile: true },
    { key: "left", header: "Left", render: (b) => <span className="tabular">{formatCurrency(b.left)}</span>, sortValue: (b) => b.left },
    { key: "status", header: "Status", render: (b) => <StatusDot tone={STATUS[b.status].tone}>{STATUS[b.status].label}</StatusDot>, sortValue: (b) => ({ over: 0, warning: 1, within: 2 })[b.status] },
  ];

  if (periodError) return <ErrorState message={periodError} />;
  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-13 text-ink-2">Fiscal year
          <select className="h-9 rounded border border-rule-strong bg-sheet px-2.5 text-sm text-ink" value={scope?.fiscal_year ?? ""}
            onChange={(e) => setScope((s) => s && { ...s, fiscal_year: e.target.value })}>
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-13 text-ink-2">Period
          <select className="h-9 rounded border border-rule-strong bg-sheet px-2.5 text-sm text-ink" value={scope?.period ?? ""}
            onChange={(e) => setScope((s) => s && { ...s, period: e.target.value })}>
            {periods.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        {current && scope && (scope.fiscal_year !== current.fiscal_year || scope.period !== current.period) && (
          <p className="pb-2 text-13 text-ink-3">Current period: {current.period} {current.fiscal_year}</p>
        )}
      </div>

      <LedgerStrip cols={5} loading={loading && !budgets} label="Budget totals">
        <MetricCard label="Budgeted" value={formatCurrency(totals.amount)} />
        <MetricCard label="Invoiced" value={formatCurrency(totals.consumed)} hint="consumed" />
        <MetricCard label="Approved, not invoiced" value={formatCurrency(totals.committed)} hint="committed" />
        <MetricCard label="Awaiting approval" value={formatCurrency(totals.pending)} hint="pending" />
        <MetricCard label="Left" value={formatCurrency(totals.left)} tone={totals.left < 0 ? "danger" : "neutral"} />
      </LedgerStrip>

      {canEdit && current && scope && <BudgetPlanningActions period={{ ...current, ...scope }} onChanged={reload} />}

      <Section title={`Budgets for ${scope?.period ?? ""} ${scope?.fiscal_year ?? ""}`}
        subtitle="A request counts from the moment it's created; rejected and cancelled requests stop counting.">
        <DataTable columns={columns} rows={budgets ?? []} rowKey={(b) => b.id} loading={loading && !budgets}
          emptyTitle="No budgets for this period"
          emptyDescription={canEdit ? "Add one above or import a CSV. Requests without a budget follow the rule budget.no_budget_policy." : "Finance sets budgets per department and category."}
          onRowClick={(b) => navigate(`/app/budgets/${b.id}`)} />
      </Section>
    </div>
  );
}
