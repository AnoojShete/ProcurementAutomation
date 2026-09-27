import { RiskBadge } from "@/components/ui/Badge";
import { titleCase } from "@/lib/format";
import type { PurchaseRequest, VendorRisk } from "@/types/api";

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

  return (
    <div className="rounded-md border border-surface-border bg-white">
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
          <span className="capitalize">{request.request_type ?? "—"}</span>
        </AssessmentRow>
        <AssessmentRow label="Policy routing">
          {chain.length ? `${chain.map(titleCase).join(" → ")}` : "Auto-approved (below threshold)"}
        </AssessmentRow>
        <AssessmentRow label="Duplicate detection">
          <Unavailable reason="Duplicate checks run on uploaded documents, not purchase requests directly" />
        </AssessmentRow>
        <AssessmentRow label="Budget status">
          <Unavailable reason="No budget-tracking API is exposed by the current backend" />
        </AssessmentRow>
      </div>
    </div>
  );
}
