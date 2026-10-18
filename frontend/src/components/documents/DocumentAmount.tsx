import { formatCurrency, formatDate } from "@/lib/format";
import type { DocumentRecord } from "@/types/api";

/** A document's total as printed (its own currency) and, for a foreign
 * currency, the INR amount the platform uses with the rate it was
 * converted at. That rate was fixed when the document was processed. */
export function DocumentAmount({ doc }: { doc: DocumentRecord }) {
  const total = doc.extracted_fields?.total;
  if (total == null) return <>—</>;
  const currency = (doc.fx?.currency ?? (doc.extracted_fields?.currency as string | undefined) ?? "INR").toUpperCase();
  const printed = formatMoney(Number(total), currency);
  if (currency === "INR" || !doc.fx) return <>{printed}</>;
  return (
    <>
      {printed}{" "}
      <span className="text-slate-500" title={`${doc.fx.source ?? "Exchange rate"}, fixed when the document was processed`}>
        ≈ {formatMoney(doc.fx.total_inr, "INR")}
        {doc.fx.rate != null && <> at {doc.fx.rate.toFixed(2)}{doc.fx.rate_date ? ` (${formatDate(doc.fx.rate_date)})` : ""}</>}
      </span>
    </>
  );
}

function formatMoney(amount: number, currency: string) {
  try {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 2 }).format(amount);
  } catch {
    return formatCurrency(amount, currency);
  }
}
