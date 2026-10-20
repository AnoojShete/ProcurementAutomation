import { useState } from "react";
import { gstApi } from "@/api/gst";
import { MsmeDeadlinesSection, TdsRegisterSection, TdsSectionsTable } from "@/components/approvals/TdsActions";
import { GstInvoicesSection, GstRatesTable, Gstr2bReconciliation } from "@/components/documents/GstActions";
import { ErrorState } from "@/components/ui/ErrorState";
import { LedgerStrip, MetricCard } from "@/components/ui/MetricCard";
import { Tabs } from "@/components/ui/Tabs";
import { useApi } from "@/hooks/useApi";
import { usePageHeader } from "@/hooks/usePageTitle";
import { formatCurrency } from "@/lib/format";

const thisMonth = () => new Date().toISOString().slice(0, 7);

/** GST and TDS (feature expansion Phase 4): the month's tax checks and
 * input tax, GSTR-2B reconciliation, TDS kept at booking, MSME deadlines,
 * and the rate tables. Each part belongs to its agent's component. */
export function GstPage() {
  usePageHeader("GST and TDS");
  const [month, setMonth] = useState(thisMonth());
  const [tab, setTab] = useState("gst");
  const { data: s, loading, error, reload } = useApi(() => gstApi.summary(month), [month]);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  const input = s ? s.input_tax.cgst + s.input_tax.sgst + s.input_tax.igst : null;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-13 text-ink-2">Month
          <input type="month" className="h-9 rounded border border-rule-strong bg-sheet px-2.5 text-sm text-ink" value={month}
            max={thisMonth()} onChange={(e) => e.target.value && setMonth(e.target.value)} />
        </label>
        {s?.buyer_gstin && <p className="pb-2 text-13 text-ink-3">Our GSTIN <span className="font-mono text-ink-2">{s.buyer_gstin}</span> (rule gst.buyer_gstin)</p>}
      </div>

      <LedgerStrip cols={5} loading={loading && !s} label="GST this month">
        <MetricCard label="Invoices checked" value={s?.invoices ?? "—"} hint={s ? `${s.by_status.ok} correct` : undefined} />
        <MetricCard label="GST problems" value={s?.by_status.flagged ?? "—"} tone={s?.by_status.flagged ? "danger" : "neutral"} hint="in review" />
        <MetricCard label="Input tax on correct invoices" value={formatCurrency(input)} hint={s ? `${formatCurrency(s.itc_eligible_inr)} claimable` : undefined} />
        <MetricCard label="Reverse charge payable" value={formatCurrency(s?.reverse_charge_payable_inr)} hint="imported services" />
        <MetricCard label="ITC at risk (last 2B)" value={s?.last_2b ? formatCurrency(s.last_2b.itc_at_risk_inr) : "No 2B yet"}
          tone={s?.last_2b?.itc_at_risk_inr ? "warning" : "neutral"} hint={s?.last_2b ? `${s.last_2b.missing_in_2b} missing` : undefined} />
      </LedgerStrip>

      <Tabs active={tab} onChange={setTab} tabs={[
        { key: "gst", label: "GST" },
        { key: "tds", label: "TDS and MSME" },
        { key: "rates", label: "Rates" },
      ]} />

      {tab === "gst" && (
        <>
          <GstInvoicesSection month={month} />
          <Gstr2bReconciliation />
        </>
      )}
      {tab === "tds" && (
        <>
          <MsmeDeadlinesSection />
          <TdsRegisterSection />
        </>
      )}
      {tab === "rates" && (
        <>
          <GstRatesTable />
          <TdsSectionsTable />
        </>
      )}
    </div>
  );
}
