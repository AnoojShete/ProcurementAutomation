import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "@/api/client";
import { sourcingApi } from "@/api/sourcing";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { formatCurrency } from "@/lib/format";
import type { RfqDetail, VendorSummary } from "@/types/api";

/** Every RFQ action (Phase 3b; finance and admin): issue an RFQ, record a
 * quote, extend the deadline, close, start another round, award, cancel.
 * Calls only the approval agent's API. */

const field = "h-9 w-full rounded border border-rule-strong bg-sheet px-2.5 text-sm text-ink focus:border-accent";
const label = "flex flex-col gap-1 text-13 text-ink-2";

function message(e: unknown, fallback: string) {
  return e instanceof ApiError ? e.message : fallback;
}

/** A datetime-local value a few days ahead, at 17:00. */
function inDays(days: number) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  d.setHours(17, 0, 0, 0);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
const iso = (local: string) => new Date(local).toISOString();

export function NewRfq({ vendors }: { vendors: VendorSummary[] }) {
  const navigate = useNavigate();
  const [form, setForm] = useState({ title: "", department: "", request_type: "hardware" as "hardware" | "license" | "saas",
                                     deadline: inDays(7), sealed: true });
  const [lines, setLines] = useState([{ name: "", quantity: "1" }]);
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const items = lines.filter((l) => l.name.trim()).map((l) => ({ name: l.name.trim(), quantity: Math.max(1, Math.floor(Number(l.quantity) || 1)) }));
    if (!form.title.trim() || !form.department.trim() || !items.length) return setError("A title, a department and at least one item are needed.");
    if (picked.length < 2) return setError("Invite at least two vendors (three or more is usual).");
    setBusy(true);
    try {
      const res = await sourcingApi.create({ ...form, title: form.title.trim(), department: form.department.trim(), items,
                                             vendor_ids: picked, deadline: iso(form.deadline) });
      navigate(`/app/sourcing/${res.data.id}`);
    } catch (err) {
      setError(message(err, "Unable to issue the RFQ."));
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader title="Issue an RFQ" subtitle="Vendors quote the RFQ reference on their quote; quotes e-mailed or dropped in the inbox are linked automatically." />
      <CardBody>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:items-end">
            <label className={`${label} lg:col-span-2`}>Title
              <input className={field} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Laptop refresh, Q3" />
            </label>
            <label className={label}>Department
              <input className={field} value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} placeholder="Engineering" />
            </label>
            <label className={label}>Type
              <select className={field} value={form.request_type} onChange={(e) => setForm({ ...form, request_type: e.target.value as typeof form.request_type })}>
                <option value="hardware">Hardware</option><option value="license">Software licence</option><option value="saas">SaaS</option>
              </select>
            </label>
          </div>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-13 text-ink-2">Items</legend>
            {lines.map((l, i) => (
              <div key={i} className="grid grid-cols-[1fr_6rem_auto] gap-2">
                <input aria-label={`Item ${i + 1}`} className={field} value={l.name} placeholder="Developer laptop, 32 GB, 3-year warranty"
                  onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                <input aria-label={`Quantity ${i + 1}`} className={field} type="number" min={1} value={l.quantity}
                  onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)))} />
                <Button size="sm" variant="ghost" disabled={lines.length === 1} onClick={() => setLines(lines.filter((_, j) => j !== i))}>Remove</Button>
              </div>
            ))}
            <div><Button size="sm" variant="ghost" onClick={() => setLines([...lines, { name: "", quantity: "1" }])}>Add a line</Button></div>
          </fieldset>
          <fieldset>
            <legend className="mb-1 text-13 text-ink-2">Vendors to invite ({picked.length} chosen)</legend>
            <div className="grid max-h-48 grid-cols-1 gap-1 overflow-y-auto rounded border border-rule p-2 sm:grid-cols-2 lg:grid-cols-3">
              {vendors.filter((v) => v.status !== "offboarded").map((v) => (
                <label key={v.id} className="flex items-center gap-2 text-13 text-ink">
                  <input type="checkbox" checked={picked.includes(v.id)}
                    onChange={(e) => setPicked(e.target.checked ? [...picked, v.id] : picked.filter((x) => x !== v.id))} />
                  {v.name}{v.risk_band ? <span className="text-ink-3">· {v.risk_band} risk</span> : null}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:items-end">
            <label className={label}>Quotes due by
              <input className={field} type="datetime-local" value={form.deadline} onChange={(e) => setForm({ ...form, deadline: e.target.value })} />
            </label>
            <label className="flex items-center gap-2 pb-2 text-13 text-ink">
              <input type="checkbox" checked={form.sealed} onChange={(e) => setForm({ ...form, sealed: e.target.checked })} />
              Sealed: nobody sees amounts until the deadline
            </label>
          </div>
          <div className="flex items-center gap-3">
            <Button type="submit" loading={busy}>Issue RFQ</Button>
            {error && <p role="alert" className="text-13 text-danger-600">{error}</p>}
          </div>
        </form>
      </CardBody>
    </Card>
  );
}

function RecordQuote({ rfq, onChanged }: { rfq: RfqDetail; onChanged: () => void }) {
  const invited = rfq.invitations.filter((i) => i.round === rfq.round);
  const [form, setForm] = useState({ vendor_id: invited[0]?.vendor_id ?? "", total: "", lead: "", warranty: "", support: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setDone(null);
    const total = Number(form.total);
    if (!form.vendor_id || !Number.isFinite(total) || total <= 0) return setError("Choose the vendor and enter the quoted total.");
    setBusy(true);
    try {
      await sourcingApi.recordResponse(rfq.id, { vendor_id: form.vendor_id, total_inr: total, lead_time_days: num(form.lead),
                                                 warranty_months: num(form.warranty), support_rating: num(form.support) });
      setDone(`Quote from ${invited.find((i) => i.vendor_id === form.vendor_id)?.vendor_name ?? "the vendor"} recorded${rfq.sealed ? " (sealed until the deadline)" : ""}.`);
      setForm({ ...form, total: "", lead: "", warranty: "", support: "" });
      onChanged();
    } catch (err) {
      setError(message(err, "Unable to record the quote."));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-3 sm:grid-cols-3 lg:grid-cols-6 lg:items-end">
      <label className={`${label} lg:col-span-2`}>Vendor
        <select className={field} value={form.vendor_id} onChange={(e) => setForm({ ...form, vendor_id: e.target.value })}>
          {invited.map((i) => <option key={i.vendor_id} value={i.vendor_id}>{i.vendor_name ?? i.vendor_id.slice(0, 8)}{i.responded_at ? " (replace quote)" : ""}</option>)}
        </select>
      </label>
      <label className={label}>Total (₹)<input className={field} inputMode="decimal" value={form.total} onChange={(e) => setForm({ ...form, total: e.target.value })} /></label>
      <label className={label}>Lead time (days)<input className={field} inputMode="numeric" value={form.lead} onChange={(e) => setForm({ ...form, lead: e.target.value })} /></label>
      <label className={label}>Warranty (months)<input className={field} inputMode="numeric" value={form.warranty} onChange={(e) => setForm({ ...form, warranty: e.target.value })} /></label>
      <label className={label}>Support (1–5)
        <select className={field} value={form.support} onChange={(e) => setForm({ ...form, support: e.target.value })}>
          <option value="">Not rated</option>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </label>
      <div className="flex items-center gap-3 sm:col-span-3 lg:col-span-6">
        <Button type="submit" variant="secondary" loading={busy}>Record quote</Button>
        {error && <p role="alert" className="text-13 text-danger-600">{error}</p>}
        {done && <p role="status" className="text-13 text-success-700">{done}</p>}
      </div>
    </form>
  );
}

/** The RFQ page's action card. */
export function SourcingActions({ rfq, onChanged }: { rfq: RfqDetail; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deadline, setDeadline] = useState(inDays(3));
  const responders = (rfq.comparison?.ranked ?? []).map((r) => r.vendor_id);
  const [shortlist, setShortlist] = useState<string[]>([]);
  const invited = rfq.invitations.filter((i) => i.round === rfq.round);
  const everyone = invited.length > 0 && invited.every((i) => i.responded_at);
  const past = new Date(rfq.deadline) <= new Date();

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (err) {
      setError(message(err, "That didn't work."));
    } finally {
      setBusy(null);
    }
  };

  if (rfq.status === "awarded" || rfq.status === "cancelled") return null;
  return (
    <Card>
      <CardHeader title={rfq.status === "open" ? "Collect quotes" : "Decide"}
        subtitle={rfq.status === "open"
          ? `Round ${rfq.round}: ${invited.filter((i) => i.responded_at).length} of ${invited.length} vendors have quoted.`
          : "Award the best response to create its purchase request, or shortlist vendors for another round."} />
      <CardBody className="flex flex-col gap-4">
        {rfq.status === "open" && <RecordQuote rfq={rfq} onChanged={onChanged} />}
        <div className="flex flex-wrap items-end gap-3 border-t border-rule pt-4">
          {rfq.status === "open" && (
            <>
              <label className={label}>New deadline
                <input className={field} type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
              </label>
              <Button variant="ghost" loading={busy === "extend"} onClick={() => act("extend", () => sourcingApi.extend(rfq.id, iso(deadline)))}>Extend deadline</Button>
              <Button variant="secondary" loading={busy === "close"} disabled={!past && !everyone}
                title={!past && !everyone ? "Closes at the deadline, or earlier once every vendor has quoted" : undefined}
                onClick={() => act("close", () => sourcingApi.close(rfq.id))}>Close and compare</Button>
            </>
          )}
          {rfq.status === "closed" && responders.length > 0 && (
            <>
              <fieldset className="flex flex-col gap-1">
                <legend className="text-13 text-ink-2">Shortlist for round {rfq.round + 1}</legend>
                {(rfq.comparison?.ranked ?? []).map((r) => (
                  <label key={r.vendor_id} className="flex items-center gap-2 text-13 text-ink">
                    <input type="checkbox" checked={shortlist.includes(r.vendor_id)}
                      onChange={(e) => setShortlist(e.target.checked ? [...shortlist, r.vendor_id] : shortlist.filter((x) => x !== r.vendor_id))} />
                    {r.vendor_name}
                  </label>
                ))}
              </fieldset>
              <label className={label}>Round {rfq.round + 1} deadline
                <input className={field} type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
              </label>
              <Button variant="secondary" disabled={!shortlist.length} loading={busy === "round"}
                onClick={() => act("round", () => sourcingApi.nextRound(rfq.id, shortlist, iso(deadline)))}>Start round {rfq.round + 1}</Button>
            </>
          )}
          <Button variant="ghost" loading={busy === "cancel"} onClick={() => {
            const reason = window.prompt("Why is this RFQ cancelled?");
            if (reason) act("cancel", () => sourcingApi.cancel(rfq.id, reason));
          }}>Cancel RFQ</Button>
        </div>
        {error && <p role="alert" className="text-13 text-danger-600">{error}</p>}
      </CardBody>
    </Card>
  );
}

/** One row's award button in the comparison table. */
export function AwardButton({ rfq, responseId, vendorName, total, onAwarded }: {
  rfq: RfqDetail; responseId: string; vendorName: string | null; total: number; onAwarded: (requestId: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (rfq.status !== "closed") return null;
  const award = async () => {
    if (!window.confirm(`Award ${rfq.reference} to ${vendorName ?? "this vendor"} for ${formatCurrency(total)}? This creates the purchase request.`)) return;
    setBusy(true);
    setError(null);
    try {
      const res = await sourcingApi.award(rfq.id, responseId);
      onAwarded(res.data.request.id);
    } catch (err) {
      setError(message(err, "Unable to award."));
      setBusy(false);
    }
  };
  return (
    <span className="flex flex-col items-end gap-1">
      <Button size="sm" loading={busy} onClick={award}>Award</Button>
      {error && <span role="alert" className="text-13 text-danger-600">{error}</span>}
    </span>
  );
}
