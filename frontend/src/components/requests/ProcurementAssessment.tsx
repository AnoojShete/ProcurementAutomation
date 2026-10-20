import { Link } from "react-router-dom";
import { budgetsApi } from "@/api/budgets";
import { Badge, RiskBadge } from "@/components/ui/Badge";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { formatCurrency, titleCase } from "@/lib/format";
import type { BudgetRoutingReason, PurchaseRequest, RequestBudgetLine, VendorRisk } from "@/types/api";

function AssessmentRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 py-2.5">
      <span className="text-sm text-slate-500">{label}</span>
      <span className="text-right text-sm text-slate-800">{children}</span>
    </div>
  );
}

function Unavailable({ reason }: { reason: string }) {
  return <span className="text-xs italic text-slate-400" title={reason}>Not available</span>;
}

const ROUTING_LABELS: Record<BudgetRoutingReason, string> = {
  over_budget: "over budget",
  no_budget: "no budget set",
  high_risk_vendor: "high-risk vendor",
  catalog_preapproved: "pre-approved catalog price",
};

/** Phase 3: where the price came from (catalog, RFQ) and any sourcing notes. */
function SourcingLine({ request }: { request: PurchaseRequest }) {
  const fromCatalog = (request.items ?? []).some((i) => (i as Record<string, unknown>).catalog_item_id);
  const flags = request.sourcing_flags ?? [];
  return (
    <span className="flex flex-col gap-1">
      {request.rfq_id ? (
        <span>Awarded from an RFQ · <Link to={`/app/sourcing/${request.rfq_id}`} className="underline-offset-2 hover:underline">see the comparison</Link></span>
      ) : fromCatalog ? (
        <span>Catalog price{(request.items ?? []).every((i) => (i as Record<string, unknown>).catalog_item_id) ? "" : " (with free-text lines)"}</span>
      ) : (
        <span className="text-ink-3">Price entered on the request</span>
      )}
      {flags.map((f) => <span key={f.code} className="text-13 text-warning-700">{f.message}</span>)}
    </span>
  );
}

const CATEGORY_LABELS: Record<string, string> = { hardware: "hardware", software: "software", saas: "SaaS", services: "IT services" };

function BudgetLine({ line, canOpen }: { line: RequestBudgetLine | null; canOpen: boolean }) {
  if (!line) return <span className="text-slate-400">Loading…</span>;
  if (!line.applies) return <Unavailable reason="Reclaims and reinstatements move seats; they don't spend budget" />;
  const check = line.check;
  const scope = check ? `${check.department} · ${CATEGORY_LABELS[check.category ?? ""] ?? check.category} · ${check.period} ${check.fiscal_year}` : "";
  if (!check || line.status_at_creation === "no_budget" || !line.budget) {
    return (
      <span className="flex flex-col items-end gap-0.5">
        <Badge tone="neutral">No budget set</Badge>
        {scope && <span className="text-caption text-ink-3">{scope}</span>}
      </span>
    );
  }
  const tone = line.status_at_creation === "over" ? "danger" : line.status_at_creation === "warning" ? "warning" : "success";
  const label = line.status_at_creation === "over" ? "Over budget" : line.status_at_creation === "warning" ? "Near the limit" : "Within budget";
  const left = check.left_after ?? 0;
  const figure = left < 0 ? `${formatCurrency(-left)} over after this request` : `${formatCurrency(left)} left after this request`;
  return (
    <span className="flex flex-col items-end gap-0.5">
      <Badge tone={tone}>{label}</Badge>
      <span className="tabular">{figure}</span>
      <span className="text-caption text-ink-3">
        {canOpen ? <Link to={`/app/budgets/${line.budget.id}`} className="underline-offset-2 hover:underline">{scope}</Link> : scope}
        {" · now "}{formatCurrency(line.budget.left)} left
      </span>
    </span>
  );
}

export function ProcurementAssessment({
  request,
  vendorRisk,
  vendorRiskLoading,
}: {
  request: PurchaseRequest;
  vendorRisk: VendorRisk | null;
  vendorRiskLoading: boolean;
}) {
  const chain = request.approval_chain ?? [];
  const { user } = useAuth();
  const { data: budgetLine } = useApi(() => budgetsApi.forRequest(request.id), [request.id]);
  const routing = request.budget_check?.routing ?? [];
  const added = routing.filter((r) => r !== "catalog_preapproved").map((r) => ROUTING_LABELS[r] ?? r);

  return (
    <div className="rounded-md border border-surface-border bg-sheet">
      <div className="border-b border-surface-border px-4 py-2.5">
        <h3 className="text-sm font-semibold text-slate-900">Procurement checks</h3>
      </div>
      <div className="divide-y divide-surface-border px-4">
        <AssessmentRow label="Vendor risk">
          {!request.vendor_id ? (
            <Unavailable reason="No vendor linked to this request" />
          ) : vendorRiskLoading ? (
            <span className="text-slate-400">Loading…</span>
          ) : vendorRisk ? (
            <RiskBadge band={vendorRisk.risk_band} />
          ) : (
            <Unavailable reason="Vendor has not been risk-scored yet" />
          )}
        </AssessmentRow>
        {vendorRisk?.top_factors?.length ? (
          <AssessmentRow label="Primary risk factor">
            {titleCase(vendorRisk.top_factors[0].feature)}
          </AssessmentRow>
        ) : null}
        <AssessmentRow label="Spend category">
          <span>{titleCase(request.request_type)}</span>
        </AssessmentRow>
        <AssessmentRow label="Policy routing">
          {chain.length ? `${chain.map(titleCase).join(" → ")}` : request.spend_tier === "catalog" ? "Auto-approved (pre-approved catalog price)" : "Auto-approved (below threshold)"}
          {added.length > 0 && <span className="block text-caption text-ink-3">Finance step added: {added.join(", ")}</span>}
          {routing.includes("catalog_preapproved") && chain.length > 0 && <span className="block text-caption text-ink-3">Manager step skipped: pre-approved catalog price</span>}
        </AssessmentRow>
        <AssessmentRow label="Duplicate detection">
          <Unavailable reason="Duplicate checks run on uploaded documents, not purchase requests directly" />
        </AssessmentRow>
        <AssessmentRow label="Sourcing">
          <SourcingLine request={request} />
        </AssessmentRow>
        <AssessmentRow label="Budget">
          <BudgetLine line={budgetLine} canOpen={["approver", "finance", "admin"].includes(user?.role ?? "")} />
        </AssessmentRow>
      </div>
    </div>
  );
}
