import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "@/api/client";
import { tdsApi } from "@/api/tds";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, Section } from "@/components/ui/Card";
import { StatusDot } from "@/components/ui/Badge";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { formatCurrency, formatDate } from "@/lib/format";
import type { MsmeDeadline, TdsRegisterEntry, TdsSection, VendorTaxInput } from "@/types/api";

const field = "h-9 w-full rounded border border-rule-strong bg-sheet px-2.5 text-sm text-ink focus:border-accent";
const message = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

function useCanEdit() {
  const { user } = useAuth();
  return user?.role === "finance" || user?.role === "admin";
}

// ── vendor tax profile (vendor page) ────────────────────────────────────────

const EMPTY: VendorTaxInput = { pan: null, tds_section: null, ldc_rate_pct: null, ldc_valid_until: null,
  msme_udyam_number: null, msme_category: null, annual_turnover_inr: null };

/** PAN, TDS section, lower-deduction certificate, MSME registration and
 * turnover of a vendor (approval-inventory-agent's /tds API). Finance and
 * admin edit it; approvers see it. */
export function VendorTaxProfileCard({ vendorId }: { vendorId: string }) {
  const canEdit = useCanEdit();
  const { data: profile, reload } = useApi(() => tdsApi.vendor(vendorId), [vendorId]);
  const { data: sections } = useApi(() => tdsApi.sections(), []);
  const [form, setForm] = useState<VendorTaxInput>(EMPTY);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (profile) setForm({ pan: profile.pan, tds_section: profile.tds_section, ldc_rate_pct: profile.ldc_rate_pct,
      ldc_valid_until: profile.ldc_valid_until, msme_udyam_number: profile.msme_udyam_number,
      msme_category: profile.msme_category, annual_turnover_inr: profile.annual_turnover_inr });
  }, [profile]);

  if (!profile) return null;
  const set = <K extends keyof VendorTaxInput>(key: K, value: VendorTaxInput[K]) => setForm((f) => ({ ...f, [key]: value }));
  const save = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await tdsApi.saveVendor(vendorId, form);
      setEditing(false);
      setSaved(true);
      reload();
    } catch (e) {
      setError(message(e, "Unable to save the tax profile."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader title="Tax profile" subtitle="Used for TDS when this vendor's invoices are booked, and for MSME payment deadlines"
        action={canEdit && !editing ? <Button size="sm" variant="secondary" onClick={() => { setEditing(true); setSaved(false); }}>Edit</Button> : undefined} />
      <CardBody className="flex flex-col gap-3 text-13">
        {!editing ? (
          <dl className="grid grid-cols-1 gap-y-1.5">
            <Item label="PAN">{profile.pan ?? (profile.pan_from_gstin ? `Not entered (GSTIN says ${profile.pan_from_gstin})` : "Not entered: TDS at the higher rate")}</Item>
            <Item label="TDS section">{profile.tds_section ?? "By purchase category"}</Item>
            {profile.ldc_rate_pct != null && <Item label="Lower deduction certificate">{profile.ldc_rate_pct}% until {formatDate(profile.ldc_valid_until)}</Item>}
            <Item label="MSME">{profile.msme_category ? `${profile.msme_category[0].toUpperCase()}${profile.msme_category.slice(1)} enterprise, ${profile.msme_udyam_number}` : "Not registered"}</Item>
            <Item label="Yearly turnover">{profile.annual_turnover_inr != null ? formatCurrency(profile.annual_turnover_inr) : "Not entered"}</Item>
          </dl>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Label text="PAN"><input className={field} value={form.pan ?? ""} placeholder={profile.pan_from_gstin ?? "AABCD5678E"}
              onChange={(e) => set("pan", e.target.value.toUpperCase() || null)} /></Label>
            <Label text="TDS section">
              <select className={field} value={form.tds_section ?? ""} onChange={(e) => set("tds_section", e.target.value || null)}>
                <option value="">By purchase category</option>
                {(sections ?? []).filter((s) => s.active).map((s) => <option key={s.section} value={s.section}>{s.section}: {s.description}</option>)}
              </select>
            </Label>
            <Label text="Lower deduction rate (%)"><input className={field} type="number" min={0} step="0.01" value={form.ldc_rate_pct ?? ""}
              onChange={(e) => set("ldc_rate_pct", e.target.value === "" ? null : Number(e.target.value))} /></Label>
            <Label text="Certificate valid until"><input className={field} type="date" value={form.ldc_valid_until ?? ""}
              onChange={(e) => set("ldc_valid_until", e.target.value || null)} /></Label>
            <Label text="Udyam number"><input className={field} value={form.msme_udyam_number ?? ""} placeholder="UDYAM-KR-03-0012345"
              onChange={(e) => set("msme_udyam_number", e.target.value.toUpperCase() || null)} /></Label>
            <Label text="MSME category">
              <select className={field} value={form.msme_category ?? ""} onChange={(e) => set("msme_category", (e.target.value || null) as VendorTaxInput["msme_category"])}>
                <option value="">Not registered</option>
                <option value="micro">Micro</option>
                <option value="small">Small</option>
                <option value="medium">Medium (no 45-day rule)</option>
              </select>
            </Label>
            <Label text="Yearly turnover (INR)"><input className={field} type="number" min={0} value={form.annual_turnover_inr ?? ""}
              onChange={(e) => set("annual_turnover_inr", e.target.value === "" ? null : Number(e.target.value))} /></Label>
            <div className="flex items-end gap-2">
              <Button loading={saving} onClick={save}>Save</Button>
              <Button variant="ghost" onClick={() => { setEditing(false); setError(null); }}>Cancel</Button>
            </div>
          </div>
        )}
        {error && <InlineError message={error} />}
        {saved && <InlineSuccess message="Tax profile saved. It applies to invoices booked from now on." />}
      </CardBody>
    </Card>
  );
}

// ── GST and TDS page ────────────────────────────────────────────────────────

/** TDS kept with each booked invoice this financial year, with totals per
 * quarter and section. */
export function TdsRegisterSection() {
  const { data, loading } = useApi(() => tdsApi.register(), []);
  const columns: Column<TdsRegisterEntry>[] = [
    { key: "invoice", header: "Invoice", render: (i) => <Link to={`/app/documents/${i.document_id}`} className="text-accent hover:underline">{i.invoice_number ?? i.document_id.slice(0, 8)}</Link> },
    { key: "vendor", header: "Vendor", render: (i) => i.vendor_id ? <Link to={`/app/vendors/${i.vendor_id}`} className="hover:underline">{i.vendor_name}</Link> : "—", hideOnMobile: true },
    { key: "date", header: "Date", render: (i) => formatDate(i.invoice_date), sortValue: (i) => i.invoice_date, hideOnMobile: true },
    { key: "section", header: "Section", render: (i) => `${i.tds_section}${i.tds_rate_pct != null ? ` · ${i.tds_rate_pct}%` : ""}` },
    { key: "base", header: "On", render: (i) => <span className="tabular">{formatCurrency(i.tds_base)}</span>, hideOnMobile: true },
    { key: "tds", header: "TDS", render: (i) => <span className="tabular" title={i.notes.join(" ")}>{formatCurrency(i.tds_amount)}</span>, sortValue: (i) => i.tds_amount ?? 0 },
    { key: "net", header: "Net payable", render: (i) => <span className="tabular">{formatCurrency(i.net_payable)}</span> },
  ];
  return (
    <Section title={`TDS register ${data ? data.fy : ""}`}
      subtitle={data ? `${formatCurrency(data.tds_total)} to deduct and deposit; totals per quarter for the TDS return: ${data.totals.map((t) => `${t.quarter} ${t.section} ${formatCurrency(t.tds)}`).join(" · ") || "none yet"}` : undefined}>
      <DataTable columns={columns} rows={data?.invoices ?? []} rowKey={(i) => i.document_id} loading={loading && !data}
        emptyTitle="No booked invoices with TDS this year" emptyDescription="TDS is worked out when an invoice is matched to its purchase request." />
    </Section>
  );
}

const MSME_TONE = { ok: "success", due_soon: "warning", overdue: "danger", paid: "neutral" } as const;

/** Unpaid invoices of micro and small enterprises with their 45-day
 * deadline; finance records a payment made at the bank. */
export function MsmeDeadlinesSection() {
  const canEdit = useCanEdit();
  const { data, loading, reload } = useApi(() => tdsApi.msme(true), []);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const paid = async (id: string) => {
    setBusy(id);
    setError(null);
    try {
      await tdsApi.recordPaid(id, {});
      reload();
    } catch (e) {
      setError(message(e, "Unable to record the payment."));
    } finally {
      setBusy(null);
    }
  };
  const columns: Column<MsmeDeadline>[] = [
    { key: "invoice", header: "Invoice", render: (i) => <Link to={`/app/documents/${i.document_id}`} className="text-accent hover:underline">{i.invoice_number ?? i.document_id.slice(0, 8)}</Link> },
    { key: "vendor", header: "Vendor", render: (i) => <Link to={`/app/vendors/${i.vendor_id}`} className="hover:underline">{i.vendor_name} ({i.msme_category})</Link> },
    { key: "amount", header: "Net payable", render: (i) => <span className="tabular">{formatCurrency(i.net_payable ?? i.amount)}</span>, hideOnMobile: true },
    { key: "due", header: "Pay by", render: (i) => formatDate(i.due_date), sortValue: (i) => i.due_date },
    { key: "status", header: "Status", render: (i) => <StatusDot tone={MSME_TONE[i.status]}>
        {i.status === "overdue" ? `${-i.days_left} days late` : i.status === "paid" ? `Paid ${formatDate(i.paid_at)}` : `${i.days_left} days left`}</StatusDot>, sortValue: (i) => i.days_left },
    ...(canEdit ? [{ key: "act", header: "", render: (i: MsmeDeadline) => i.status !== "paid" &&
        <Button size="sm" variant="secondary" loading={busy === i.document_id} onClick={() => paid(i.document_id)}>Paid at the bank</Button> }] : []),
  ];
  return (
    <Section title="MSME payment deadlines" subtitle="Invoices from micro and small enterprises must be paid within the agreed period, at most 45 days from acceptance, or the expense isn't deductible this year (s. 43B(h)). Unpaid first; paid ones stay listed.">
      {error && <InlineError message={error} />}
      <DataTable columns={columns} rows={data ?? []} rowKey={(i) => i.document_id} loading={loading && !data}
        emptyTitle="No MSME invoices" emptyDescription="Mark a vendor as a micro or small enterprise on its tax profile." />
    </Section>
  );
}

/** TDS rates and thresholds per section; finance edits them. */
export function TdsSectionsTable() {
  const canEdit = useCanEdit();
  const { data, reload } = useApi(() => tdsApi.sections(), []);
  const [edit, setEdit] = useState<TdsSection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    if (!edit) return;
    setError(null);
    try {
      const { section, updated_by: _u, updated_at: _a, ...body } = edit;
      await tdsApi.saveSection(section, body);
      setEdit(null);
      reload();
    } catch (e) {
      setError(message(e, "Unable to save the section."));
    }
  };
  const num = (v: number | null) => (v == null ? "—" : formatCurrency(v));
  return (
    <Section title="TDS sections" subtitle="Seeded with the October 2026 rates; confirm them with a chartered accountant. Changes apply to invoices booked afterwards.">
      <table className="w-full text-13">
        <thead><tr className="border-b border-rule text-left text-ink-3">
          <th className="py-1.5 pr-2 font-medium">Section</th><th className="py-1.5 pr-2 font-medium">Rate</th>
          <th className="hidden py-1.5 pr-2 font-medium sm:table-cell">Without PAN</th><th className="hidden py-1.5 pr-2 font-medium sm:table-cell">Threshold</th><th />
        </tr></thead>
        <tbody>
          {(data ?? []).map((s) => edit?.section === s.section ? (
            <tr key={s.section} className="border-b border-rule">
              <td className="py-1.5 pr-2">{s.section}</td>
              <td className="w-24 py-1.5 pr-2"><input aria-label="Rate" className={field} type="number" step="0.01" value={edit.rate_pct} onChange={(e) => setEdit({ ...edit, rate_pct: Number(e.target.value) })} /></td>
              <td className="hidden w-24 py-1.5 pr-2 sm:table-cell"><input aria-label="Rate without PAN" className={field} type="number" step="0.01" value={edit.rate_no_pan_pct} onChange={(e) => setEdit({ ...edit, rate_no_pan_pct: Number(e.target.value) })} /></td>
              <td className="hidden w-36 py-1.5 pr-2 sm:table-cell"><input aria-label="Yearly threshold" className={field} type="number" value={edit.threshold_annual_inr ?? ""} onChange={(e) => setEdit({ ...edit, threshold_annual_inr: e.target.value === "" ? null : Number(e.target.value) })} /></td>
              <td className="py-1.5 text-right"><span className="inline-flex gap-1"><Button size="sm" onClick={save}>Save</Button><Button size="sm" variant="ghost" onClick={() => setEdit(null)}>Cancel</Button></span></td>
            </tr>
          ) : (
            <tr key={s.section} className="border-b border-rule last:border-0">
              <td className="py-1.5 pr-2"><span className="font-medium text-ink">{s.section}</span> <span className="text-ink-3">{s.description}</span></td>
              <td className="py-1.5 pr-2 tabular">{s.rate_pct}%</td>
              <td className="hidden py-1.5 pr-2 tabular sm:table-cell">{s.rate_no_pan_pct}%</td>
              <td className="hidden py-1.5 pr-2 tabular sm:table-cell">{s.threshold_single_inr != null ? `${num(s.threshold_single_inr)} per invoice, ` : ""}{num(s.threshold_annual_inr)} a year{s.above_threshold_only ? " (on the part above)" : ""}</td>
              <td className="py-1.5 text-right">{canEdit && <Button size="sm" variant="ghost" onClick={() => setEdit(s)}>Edit</Button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {error && <InlineError message={error} />}
    </Section>
  );
}

function Item({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-rule py-1 last:border-0">
      <dt className="text-ink-3">{label}</dt>
      <dd className="text-right text-ink">{children}</dd>
    </div>
  );
}

function Label({ text, children }: { text: string; children: React.ReactNode }) {
  return <label className="flex flex-col gap-1 text-13 text-ink-2">{text}{children}</label>;
}

