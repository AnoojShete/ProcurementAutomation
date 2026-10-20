import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Upload } from "lucide-react";
import { ApiError } from "@/api/client";
import { gstApi } from "@/api/gst";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/Button";
import { Section } from "@/components/ui/Card";
import { StatusDot } from "@/components/ui/Badge";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { InlineError } from "@/components/ui/ErrorState";
import { formatCurrency, formatDate, formatDateTime } from "@/lib/format";
import { TAX_STATUS } from "./TaxCheckSection";
import type { GstInvoice, GstRate, Gstr2bRow, Gstr2bUpload } from "@/types/api";

const field = "h-9 w-full rounded border border-rule-strong bg-sheet px-2.5 text-sm text-ink focus:border-accent";
const message = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

/** The month's invoices with their GST check (document-vendor-agent). */
export function GstInvoicesSection({ month }: { month: string }) {
  const [status, setStatus] = useState("");
  const { data, loading } = useApi(() => gstApi.invoices(month, status || undefined), [month, status]);
  const columns: Column<GstInvoice>[] = [
    { key: "invoice", header: "Invoice", render: (i) => <Link to={`/app/documents/${i.document_id}`} className="text-accent hover:underline">{i.invoice_number ?? i.document_id.slice(0, 8)}</Link> },
    { key: "vendor", header: "Vendor", render: (i) => i.vendor_name ?? "—", sortValue: (i) => (i.vendor_name ?? "").toLowerCase(), hideOnMobile: true },
    { key: "date", header: "Date", render: (i) => formatDate(i.invoice_date), sortValue: (i) => i.invoice_date ?? "", hideOnMobile: true },
    { key: "gst", header: "GST", render: (i) => <span className="tabular">{i.reverse_charge ? `${formatCurrency(i.gst_payable_inr)} payable` : formatCurrency(i.gst_total)}</span>, sortValue: (i) => i.gst_total ?? i.gst_payable_inr ?? 0 },
    { key: "status", header: "Check", render: (i) => i.status ? <span title={i.issues.join("; ")}><StatusDot tone={TAX_STATUS[i.status].tone}>{TAX_STATUS[i.status].label}</StatusDot></span> : "—", sortValue: (i) => i.status ?? "" },
    { key: "issue", header: "Why", render: (i) => <span className="text-ink-2">{i.issues[0] ?? (i.einvoice_verified ? "E-invoice QR verified" : "")}</span>, hideOnMobile: true },
  ];
  return (
    <Section title="Invoices this month" subtitle="Every invoice's GST check; a flagged one is in the review queue."
      action={
        <select aria-label="Filter by check result" className="h-8 rounded border border-rule-strong bg-sheet px-2 text-13 text-ink" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All results</option>
          {Object.entries(TAX_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
      }>
      <DataTable columns={columns} rows={data ?? []} rowKey={(i) => i.document_id} loading={loading && !data}
        emptyTitle="No invoices this month" emptyDescription="Invoices are checked when they're read." />
    </Section>
  );
}

const RESULT = {
  matched: { tone: "success", label: "Matched" },
  value_mismatch: { tone: "warning", label: "Amounts differ" },
  missing_in_2b: { tone: "danger", label: "Missing in 2B" },
  not_in_books: { tone: "warning", label: "Not in our books" },
} as const;

/** Upload the GSTR-2B JSON from the GST portal and see what reconciles. */
export function Gstr2bReconciliation() {
  const { user } = useAuth();
  const canUpload = user?.role === "finance" || user?.role === "admin";
  const { data: uploads, reload } = useApi(() => gstApi.uploads(), []);
  const [result, setResult] = useState<Gstr2bUpload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const send = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      const res = await gstApi.reconcile(file);
      setResult(res.data);
      reload();
    } catch (e) {
      setError(message(e, "Unable to read that file."));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  const open = async (id: string) => setResult((await gstApi.upload(id)).data);

  const shown = result;
  const columns: Column<Gstr2bRow>[] = [
    { key: "result", header: "Result", render: (r) => <StatusDot tone={RESULT[r.result].tone}>{RESULT[r.result].label}</StatusDot>, sortValue: (r) => r.result },
    { key: "invoice", header: "Invoice", render: (r) => r.document_id ? <Link to={`/app/documents/${r.document_id}`} className="text-accent hover:underline">{r.invoice_number}</Link> : r.invoice_number },
    { key: "supplier", header: "Supplier", render: (r) => <span>{r.supplier ?? "—"} <span className="font-mono text-ink-3">{r.supplier_gstin}</span></span>, hideOnMobile: true },
    { key: "tax", header: "Tax (ours / 2B)", render: (r) => <span className="tabular">{formatCurrency(r.tax_books ?? null)} / {formatCurrency(r.tax_2b ?? null)}</span>, hideOnMobile: true },
    { key: "detail", header: "What to do", render: (r) => <span className="text-ink-2">{r.detail}</span> },
  ];

  return (
    <Section title="GSTR-2B reconciliation"
      subtitle="Input tax credit needs the invoice in our GSTR-2B. Download the 2B JSON from the GST portal and upload it here."
      action={canUpload && (
        <>
          <input ref={input} type="file" accept="application/json,.json" className="hidden" aria-label="GSTR-2B file"
            onChange={(e) => e.target.files?.[0] && send(e.target.files[0])} />
          <Button size="sm" icon={<Upload className="size-3.5" />} loading={busy} onClick={() => input.current?.click()}>Upload 2B</Button>
        </>
      )}>
      <div className="flex flex-col gap-3 text-13">
        {error && <InlineError message={error} />}
        {(uploads ?? []).length > 0 && (
          <p className="text-ink-3">Earlier uploads:{" "}
            {uploads!.slice(0, 6).map((u, n) => (
              <span key={u.id}>{n > 0 && " · "}
                <button type="button" className="text-accent hover:underline" onClick={() => open(u.id)}>
                  {u.period.slice(0, 2)}/{u.period.slice(2)} ({formatDateTime(u.uploaded_at ?? null)})
                </button>
              </span>
            ))}
          </p>
        )}
        {shown?.rows && (
          <>
            <p className="text-ink-2">
              Return period {shown.period.slice(0, 2)}/{shown.period.slice(2)}: {shown.summary.matched} matched, {shown.summary.value_mismatch} with
              different amounts, {shown.summary.missing_in_2b} of ours missing, {shown.summary.not_in_books} not in our books.
              Input tax credit at risk: <span className="font-medium text-ink">{formatCurrency(shown.summary.itc_at_risk_inr)}</span>.
            </p>
            <DataTable columns={columns} rows={shown.rows} rowKey={(r) => `${r.result}-${r.supplier_gstin}-${r.invoice_number}`}
              emptyTitle="Nothing to reconcile" />
          </>
        )}
      </div>
    </Section>
  );
}

const CATEGORIES: GstRate["category"][] = ["hardware", "software", "saas", "services"];

/** GST rate per HSN/SAC code; finance adds or changes rows. */
export function GstRatesTable() {
  const { user } = useAuth();
  const canEdit = user?.role === "finance" || user?.role === "admin";
  const { data, reload } = useApi(() => gstApi.rates(), []);
  const [edit, setEdit] = useState<Omit<GstRate, "updated_by" | "updated_at"> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    if (!edit) return;
    setError(null);
    try {
      await gstApi.saveRate(edit);
      setEdit(null);
      reload();
    } catch (e) {
      setError(message(e, "Unable to save the rate."));
    }
  };
  return (
    <Section title="GST rates by HSN / SAC" subtitle="The longest matching code prefix decides the rate. Seeded with the October 2026 rates; confirm them with a chartered accountant."
      action={canEdit && !edit && <Button size="sm" variant="secondary" onClick={() => setEdit({ code: "", description: "", category: "services", rate_pct: 18 })}>Add code</Button>}>
      {edit && (
        <div className="mb-3 grid grid-cols-2 items-end gap-2 sm:grid-cols-5">
          <input aria-label="Code" className={field} placeholder="998313" value={edit.code} onChange={(e) => setEdit({ ...edit, code: e.target.value.trim() })} />
          <input aria-label="Description" className={`${field} sm:col-span-2`} placeholder="What it covers" value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} />
          <select aria-label="Category" className={field} value={edit.category} onChange={(e) => setEdit({ ...edit, category: e.target.value as GstRate["category"] })}>
            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <input aria-label="Rate" className={field} type="number" step="0.01" value={edit.rate_pct} onChange={(e) => setEdit({ ...edit, rate_pct: Number(e.target.value) })} />
          <span className="col-span-2 flex gap-1 sm:col-span-5"><Button size="sm" onClick={save}>Save</Button><Button size="sm" variant="ghost" onClick={() => setEdit(null)}>Cancel</Button></span>
        </div>
      )}
      {error && <InlineError message={error} />}
      <table className="w-full text-13">
        <thead><tr className="border-b border-rule text-left text-ink-3">
          <th className="py-1.5 pr-2 font-medium">Code</th><th className="py-1.5 pr-2 font-medium">Covers</th>
          <th className="hidden py-1.5 pr-2 font-medium sm:table-cell">Category</th><th className="py-1.5 pr-2 font-medium">Rate</th><th />
        </tr></thead>
        <tbody>
          {(data ?? []).map((r) => (
            <tr key={r.code} className="border-b border-rule last:border-0">
              <td className="py-1.5 pr-2 font-mono">{r.code}</td>
              <td className="py-1.5 pr-2 text-ink-2">{r.description}</td>
              <td className="hidden py-1.5 pr-2 sm:table-cell">{r.category}</td>
              <td className="py-1.5 pr-2 tabular">{r.rate_pct}%</td>
              <td className="py-1.5 text-right">{canEdit && <Button size="sm" variant="ghost" onClick={() => setEdit({ code: r.code, description: r.description, category: r.category, rate_pct: r.rate_pct })}>Edit</Button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}
