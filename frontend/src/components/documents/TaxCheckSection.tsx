import { Section } from "@/components/ui/Card";
import { StatusDot } from "@/components/ui/Badge";
import { LedgerStrip, MetricCard } from "@/components/ui/MetricCard";
import { formatCurrency } from "@/lib/format";
import type { TaxCheck, TaxStatus } from "@/types/api";

export const TAX_STATUS: Record<TaxStatus, { tone: "success" | "warning" | "danger" | "neutral" | "brand"; label: string }> = {
  ok: { tone: "success", label: "GST correct" },
  flagged: { tone: "danger", label: "GST problem" },
  incomplete: { tone: "neutral", label: "No GST breakdown" },
  reverse_charge: { tone: "brand", label: "Reverse charge" },
  import_goods: { tone: "neutral", label: "Imported goods" },
};

const SUPPLY: Record<TaxCheck["supply_type"], string> = {
  intra_state: "Within the state: CGST + SGST",
  inter_state: "Between states: IGST",
  import: "From outside India",
  unknown: "Not known",
};

/** The GST check of an invoice (Phase 4): what was read, each check and its
 * result, the signed e-invoice QR, and reverse charge. Read-only; a flagged
 * invoice is corrected or confirmed with the document's own review actions. */
export function TaxCheckSection({ tax }: { tax: TaxCheck }) {
  const status = TAX_STATUS[tax.status];
  const qr = tax.einvoice ?? { present: false };
  return (
    <Section
      title="GST check"
      subtitle={tax.status === "flagged" ? "This invoice went to review because of the problems below; the confidence score is unchanged."
        : tax.status === "reverse_charge" ? "We pay this GST ourselves and can claim it back as input tax credit."
        : "Checked when the invoice was read."}
      action={<StatusDot tone={status.tone}>{status.label}</StatusDot>}
    >
      <div className="flex flex-col gap-4 text-13">
        <LedgerStrip cols={4} label="GST figures">
          <MetricCard label="Taxable value" value={formatCurrency(tax.taxable_value)} />
          {tax.reverse_charge
            ? <MetricCard label="GST we pay (reverse charge)" value={formatCurrency(tax.gst_payable_inr)} hint={tax.expected_rate_pct != null ? `${tax.expected_rate_pct}%` : undefined} />
            : <MetricCard label="GST charged" value={formatCurrency(tax.gst_total)}
                hint={tax.effective_rate_pct != null ? `${tax.effective_rate_pct}%${tax.expected_rate_pct != null && tax.expected_rate_pct !== tax.effective_rate_pct ? `, expected ${tax.expected_rate_pct}%` : ""}` : undefined} />}
          <MetricCard label="Input tax credit" value={tax.itc_eligible ? "Can be claimed" : "Not yet"} tone={tax.itc_eligible ? "success" : "neutral"} />
          <MetricCard label="E-invoice QR" tone={qr.verified === false ? "danger" : qr.verified ? "success" : "neutral"}
            value={!qr.present ? "None" : qr.verified === false ? "Signature fails" : qr.verified ? (qr.mismatches?.length ? "Doesn't match" : "Verified") : "Not verified"} />
        </LedgerStrip>

        <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
          <Row label="Supply">{SUPPLY[tax.supply_type]}</Row>
          <Row label="Supplier GSTIN"><span className="font-mono">{tax.supplier_gstin ?? "—"}</span></Row>
          <Row label="Our GSTIN on the invoice"><span className="font-mono">{tax.buyer_gstin ?? "—"}</span></Row>
          {(tax.cgst != null || tax.sgst != null) && <Row label="CGST + SGST">{formatCurrency(tax.cgst)} + {formatCurrency(tax.sgst)}</Row>}
          {tax.igst != null && <Row label="IGST">{formatCurrency(tax.igst)}</Row>}
          {tax.hsn_codes.length > 0 && <Row label="HSN / SAC">{[...new Set(tax.hsn_codes.map((c) => c.code))].join(", ")}</Row>}
        </dl>

        {tax.checks.length > 0 && (
          <ul className="flex flex-col gap-1.5">
            {tax.checks.map((c) => (
              <li key={c.check} className="flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-3">
                <span className="shrink-0"><StatusDot tone={c.ok ? "success" : "danger"}>{c.check}</StatusDot></span>
                <span className={c.ok ? "text-ink-3" : "text-ink"}>{c.detail}</span>
              </li>
            ))}
          </ul>
        )}
        {tax.notes.length > 0 && (
          <ul className="list-disc pl-5 text-ink-2">{tax.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        )}
      </div>
    </Section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-rule py-1">
      <dt className="text-ink-3">{label}</dt>
      <dd className="text-right text-ink">{children}</dd>
    </div>
  );
}
