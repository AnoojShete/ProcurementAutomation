import { useState } from "react";
import { ApiError } from "@/api/client";
import { contractsApi } from "@/api/contracts";
import { useAuth } from "@/hooks/useAuth";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { formatCurrency, formatDate } from "@/lib/format";
import type {
  ContractObligation, ContractObligations, LicenseItem, ObligationStatus, ObligationType, SlaCredit,
} from "@/types/api";

/** Every obligation action on a signed contract (Phase 2): confirm what was
 * read from the contract, record a month's uptime, mark an obligation met,
 * breached, waived or reopened, settle SLA credits, add one by hand.
 * Calls only the contract agent's API. */

const SETTLE = ["finance", "admin"];
const RECORD = ["approver", "finance", "admin"];

/** The numbers a person can check or correct, per type (keys match the extraction). */
const FIELDS: Record<ObligationType, { key: string; label: string }[]> = {
  sla_uptime: [
    { key: "uptime_pct", label: "Uptime committed (%)" }, { key: "credit_pct_per_step", label: "Credit per step (%)" },
    { key: "step_pct", label: "Step (% below)" }, { key: "credit_cap_pct", label: "Credit cap (%)" },
  ],
  license_limit: [{ key: "seats", label: "Seats allowed" }],
  price_cap: [{ key: "max_increase_pct", label: "Largest increase (%)" }],
  audit_rights: [{ key: "days", label: "Notice before an audit (days)" }],
  warranty: [{ key: "months", label: "Warranty (months)" }],
  termination_convenience: [{ key: "days", label: "Notice to terminate (days)" }],
  minimum_commitment: [{ key: "seats", label: "Minimum seats" }, { key: "months", label: "For (months)" }],
  post_termination: [{ key: "days", label: "Days after the end" }],
  data_protection: [{ key: "breach_notice_hours", label: "Breach notice (hours)" }],
  liability_cap: [{ key: "fees_months", label: "Capped at fees of (months)" }, { key: "amount", label: "Or amount (₹)" }],
  insurance: [{ key: "amount", label: "Cover (₹)" }],
};
const LINKS_LICENCE: ObligationType[] = ["license_limit", "minimum_commitment"];

const STATUS: Record<ObligationStatus, { tone: "neutral" | "warning" | "success" | "danger" | "brand"; label: string }> = {
  to_confirm: { tone: "warning", label: "to confirm" },
  open: { tone: "brand", label: "open" },
  met: { tone: "success", label: "met" },
  breached: { tone: "danger", label: "breached" },
  waived: { tone: "neutral", label: "waived" },
};

const field = "h-9 w-full rounded border border-rule-strong bg-sheet px-2.5 text-sm text-ink focus:border-accent";
const label = "flex flex-col gap-1 text-13 text-ink-2";

function message(e: unknown, fallback: string) {
  return e instanceof ApiError ? e.message : fallback;
}

/** One line describing the terms, e.g. "99.9% uptime; 10% credit per 0.1% below, up to 50%". */
export function obligationSummary(ob: Pick<ContractObligation, "type" | "value">): string {
  const v = ob.value as Record<string, any>;
  switch (ob.type) {
    case "sla_uptime":
      return [v.uptime_pct != null && `${v.uptime_pct}% uptime`,
        v.credit_pct_per_step != null && `${v.credit_pct_per_step}% credit per ${v.step_pct ?? "?"}% below`,
        v.credit_cap_pct != null && `up to ${v.credit_cap_pct}%`].filter(Boolean).join("; ");
    case "license_limit":
      return [v.seats && `${v.seats} users`, v.non_transferable && "not transferable", v.territory && `in ${v.territory}`]
        .filter(Boolean).join(", ");
    case "price_cap": return v.max_increase_pct != null ? `increases capped at ${v.max_increase_pct}%` : "";
    case "audit_rights": return [v.frequency && `${v.frequency}`, v.days && `${v.days} days' notice`].filter(Boolean).join(", ");
    case "warranty": return v.months ? `${v.months} months` : "";
    case "termination_convenience": return v.days ? `${v.days} days' notice` : "";
    case "minimum_commitment": return [v.seats && `at least ${v.seats} seats`, v.months && `for ${v.months} months`].filter(Boolean).join(" ");
    case "post_termination": return v.days ? `within ${v.days} days of the end` : "";
    case "data_protection": return v.breach_notice_hours ? `breach notice within ${v.breach_notice_hours} hours` : "";
    case "liability_cap":
      return v.fees_months ? `fees paid in ${v.fees_months} months` : v.amount ? formatCurrency(v.amount) : "";
    case "insurance": return v.amount ? `${formatCurrency(v.amount)} cover` : "";
  }
  return "";
}

function ValueFields({ type, value, onChange }: {
  type: ObligationType; value: Record<string, string>; onChange: (v: Record<string, string>) => void;
}) {
  return (
    <>
      {FIELDS[type].map((f) => (
        <label key={f.key} className={label}>{f.label}
          <input className={field} inputMode="decimal" value={value[f.key] ?? ""}
            onChange={(e) => onChange({ ...value, [f.key]: e.target.value })} />
        </label>
      ))}
    </>
  );
}

/** Text inputs back to the stored value: numbers where numbers were typed,
 * other keys (territory, frequency…) kept as they were. */
function toValue(original: Record<string, unknown>, typed: Record<string, string>, type: ObligationType) {
  const out: Record<string, number | string | boolean> = { ...(original as Record<string, number | string | boolean>) };
  for (const f of FIELDS[type]) {
    const t = (typed[f.key] ?? "").trim();
    if (t === "") delete out[f.key];
    else if (Number.isFinite(Number(t))) out[f.key] = Number(t);
  }
  return out;
}

function ConfirmForm({ ob, licenses, onDone }: { ob: ContractObligation; licenses: LicenseItem[]; onDone: () => void }) {
  const [typed, setTyped] = useState<Record<string, string>>(
    Object.fromEntries(FIELDS[ob.type].map((f) => [f.key, ob.value[f.key] != null ? String(ob.value[f.key]) : ""])));
  const [owner, setOwner] = useState(ob.owner_email ?? "");
  const [licenseId, setLicenseId] = useState(ob.license_id ?? "");
  const [due, setDue] = useState(ob.due_date ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await contractsApi.confirmObligation(ob.id, {
        value: toValue(ob.value, typed, ob.type), owner_email: owner.trim(), license_id: licenseId,
        due_date: due || undefined,
      });
      onDone();
    } catch (err) {
      setError(message(err, "Unable to confirm the obligation."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:items-end">
      <ValueFields type={ob.type} value={typed} onChange={setTyped} />
      <label className={label}>Owner e-mail
        <input className={field} type="email" value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="it-owner@acme.test" />
      </label>
      {LINKS_LICENCE.includes(ob.type) && (
        <label className={label}>Licence it limits
          <select className={field} value={licenseId} onChange={(e) => setLicenseId(e.target.value)}>
            <option value="">Not linked</option>
            {licenses.map((l) => <option key={l.id} value={l.id}>{l.app_name} ({l.total_seats} seats)</option>)}
          </select>
        </label>
      )}
      <label className={label}>Due date (blank: worked out from the contract)
        <input className={field} type="date" value={due} onChange={(e) => setDue(e.target.value)} />
      </label>
      <div className="flex items-center gap-3 sm:col-span-2 lg:col-span-4">
        <Button type="submit" loading={busy}>{ob.status === "to_confirm" ? "Confirm" : "Save changes"}</Button>
        {error && <p role="alert" className="text-13 text-danger-600">{error}</p>}
      </div>
    </form>
  );
}

function DowntimeForm({ ob, onDone }: { ob: ContractObligation; onDone: (msg: string) => void }) {
  const lastMonth = new Date(new Date().getFullYear(), new Date().getMonth(), 0);
  const [period, setPeriod] = useState(`${lastMonth.getFullYear()}-${String(lastMonth.getMonth() + 1).padStart(2, "0")}`);
  const [uptime, setUptime] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const value = Number(uptime);
    if (!uptime.trim() || !Number.isFinite(value) || value < 0 || value > 100) {
      setError("Enter the measured uptime as a percentage, e.g. 99.5.");
      return;
    }
    setBusy(true);
    try {
      const res = await contractsApi.recordDowntime(ob.id, period, value, note.trim() || undefined);
      const c = res.data.credit;
      onDone(c ? `Credit of ${formatCurrency(c.credit_amount, c.currency)} (${c.credit_pct}%) for ${c.period} is ${c.status}.`
               : `${period}: the SLA was met, no credit.`);
      setUptime("");
      setNote("");
    } catch (err) {
      setError(message(err, "Unable to record the uptime."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-3 sm:grid-cols-4 sm:items-end">
      <label className={label}>Month
        <input className={field} type="month" value={period} onChange={(e) => setPeriod(e.target.value)} />
      </label>
      <label className={label}>Measured uptime (%)
        <input className={field} inputMode="decimal" value={uptime} onChange={(e) => setUptime(e.target.value)} placeholder="99.5" />
      </label>
      <label className={label}>Note (optional)
        <input className={field} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Status page incident #42" />
      </label>
      <Button type="submit" variant="secondary" loading={busy}>Record uptime</Button>
      {error && <p role="alert" className="text-13 text-danger-600 sm:col-span-4">{error}</p>}
    </form>
  );
}

function ObligationRow({ ob, licenses, onChanged }: { ob: ContractObligation; licenses: LicenseItem[]; onChanged: () => void }) {
  const { user } = useAuth();
  const role = user?.role ?? "";
  const canSettle = SETTLE.includes(role);
  const canRecord = RECORD.includes(role);
  const [open, setOpen] = useState(ob.status === "to_confirm" && canSettle);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const licence = licenses.find((l) => l.id === ob.license_id);
  const status = STATUS[ob.status];

  const act = async (action: "met" | "waived" | "reopened" | "breach") => {
    let note: string | undefined;
    if (action === "waived" || action === "breach") {
      const typed = window.prompt(action === "waived" ? "Why is this obligation waived?" : "What happened?");
      if (typed === null) return;
      note = typed;
    }
    setError(null);
    setDone(null);
    setBusy(action);
    try {
      await contractsApi.obligationAction(ob.id, action, note);
      setDone(action === "met" && ob.recurrence !== "none" ? "Done for this period; the next one is scheduled." : null);
      onChanged();
    } catch (err) {
      setError(message(err, "Unable to update the obligation."));
    } finally {
      setBusy(null);
    }
  };

  return (
    <li className="border-b border-rule py-3 last:border-0">
      <button type="button" className="flex w-full flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-left"
        aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="min-w-0">
          <span className="font-medium text-ink">{ob.label}</span>
          {obligationSummary(ob) && <span className="ml-2 text-13 text-ink-2">{obligationSummary(ob)}</span>}
        </span>
        <span className="flex items-center gap-3 text-13 text-ink-3">
          {ob.due_date && ob.status === "open" && <span>Due {formatDate(ob.due_date)}{ob.recurrence !== "none" ? ` (${ob.recurrence})` : ""}</span>}
          <Badge tone={status.tone}>{status.label}</Badge>
        </span>
      </button>

      {open && (
        <div className="mt-3 flex flex-col gap-3 pl-0 sm:pl-4">
          {ob.clause_text && (
            <blockquote className="border-l-2 border-rule-strong pl-3 text-13 text-ink-2">{ob.clause_text}</blockquote>
          )}
          <p className="text-13 text-ink-3">
            {ob.extracted_by === "manual" ? "Added by hand" :
              `Read by ${ob.extracted_by === "regex" ? "the clause rules" : "Legal-BERT (CUAD)"}`}
            {ob.confirmed_by && <> · confirmed by {ob.confirmed_by}</>}
            {ob.owner_email && <> · owner {ob.owner_email}</>}
            {licence && <> · limits {licence.app_name} ({licence.assigned_seats ?? 0} of {licence.total_seats} seats assigned)</>}
          </p>

          {canSettle && (ob.status === "to_confirm" || editing) && (
            <ConfirmForm ob={ob} licenses={licenses} onDone={() => { setEditing(false); onChanged(); }} />
          )}

          {ob.type === "sla_uptime" && canRecord && (ob.status === "open" || ob.status === "breached") && (
            <DowntimeForm ob={ob} onDone={(m) => { setDone(m); onChanged(); }} />
          )}

          <div className="flex flex-wrap items-center gap-2">
            {canRecord && (ob.status === "open" || ob.status === "breached") && (
              <Button size="sm" variant="secondary" loading={busy === "met"} onClick={() => act("met")}>
                {ob.recurrence === "none" ? "Mark met" : "Done for this period"}
              </Button>
            )}
            {canRecord && ob.status === "open" && (
              <Button size="sm" variant="ghost" loading={busy === "breach"} onClick={() => act("breach")}>Record a breach</Button>
            )}
            {canSettle && (ob.status === "open" || ob.status === "breached") && !editing && (
              <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>Edit terms</Button>
            )}
            {canSettle && ob.status !== "waived" && ob.status !== "met" && (
              <Button size="sm" variant="ghost" loading={busy === "waived"} onClick={() => act("waived")}>Waive</Button>
            )}
            {canSettle && (ob.status === "met" || ob.status === "waived" || ob.status === "breached") && (
              <Button size="sm" variant="ghost" loading={busy === "reopened"} onClick={() => act("reopened")}>Reopen</Button>
            )}
          </div>
          {error && <p role="alert" className="text-13 text-danger-600">{error}</p>}
          {done && <p role="status" className="text-13 text-success-700">{done}</p>}
        </div>
      )}
    </li>
  );
}

function Credits({ credits, onChanged }: { credits: SlaCredit[]; onChanged: () => void }) {
  const { user } = useAuth();
  const canSettle = SETTLE.includes(user?.role ?? "");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const settle = async (c: SlaCredit, status: "expected" | "applied" | "waived") => {
    let note: string | undefined;
    if (status === "waived") {
      const typed = window.prompt("Why is this credit waived?");
      if (typed === null) return;
      note = typed;
    }
    setError(null);
    setBusy(c.id + status);
    try {
      await contractsApi.settleCredit(c.id, status, note);
      onChanged();
    } catch (err) {
      setError(message(err, "Unable to update the credit."));
    } finally {
      setBusy(null);
    }
  };

  const tone = { proposed: "warning", expected: "warning", applied: "success", waived: "neutral" } as const;
  return (
    <div className="mt-4">
      <h4 className="mb-2 text-13 font-semibold text-ink">Service credits</h4>
      <ul className="flex flex-col">
        {credits.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-rule py-2 text-13 last:border-0">
            <span className="text-ink">
              {c.period}: {c.measured_uptime_pct}% measured, {c.credit_pct}% credit ={" "}
              <span className="font-medium">{formatCurrency(c.credit_amount, c.currency)}</span>
            </span>
            <span className="flex items-center gap-2">
              <Badge tone={tone[c.status]}>{c.status}</Badge>
              {canSettle && c.status === "proposed" && (
                <Button size="sm" variant="secondary" loading={busy === c.id + "expected"} onClick={() => settle(c, "expected")}>Expect on next invoice</Button>
              )}
              {canSettle && c.status === "expected" && (
                <Button size="sm" variant="secondary" loading={busy === c.id + "applied"} onClick={() => settle(c, "applied")}>Seen on an invoice</Button>
              )}
              {canSettle && (c.status === "proposed" || c.status === "expected") && (
                <Button size="sm" variant="ghost" loading={busy === c.id + "waived"} onClick={() => settle(c, "waived")}>Waive</Button>
              )}
            </span>
          </li>
        ))}
      </ul>
      {error && <p role="alert" className="mt-2 text-13 text-danger-600">{error}</p>}
    </div>
  );
}

function AddObligation({ contractId, licenses, onDone }: { contractId: string; licenses: LicenseItem[]; onDone: () => void }) {
  const [type, setType] = useState<ObligationType>("warranty");
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [clause, setClause] = useState("");
  const [owner, setOwner] = useState("");
  const [licenseId, setLicenseId] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await contractsApi.addObligation(contractId, {
        type, value: toValue({}, typed, type), clause_text: clause.trim() || undefined,
        owner_email: owner.trim() || undefined, license_id: licenseId || undefined, due_date: due || undefined,
      });
      setTyped({});
      setClause("");
      onDone();
    } catch (err) {
      setError(message(err, "Unable to add the obligation."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="mt-4 grid grid-cols-1 gap-3 border-t border-rule pt-4 sm:grid-cols-2 lg:grid-cols-4 lg:items-end">
      <label className={label}>Obligation
        <select className={field} value={type} onChange={(e) => { setType(e.target.value as ObligationType); setTyped({}); }}>
          {(Object.keys(FIELDS) as ObligationType[]).map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
        </select>
      </label>
      <ValueFields type={type} value={typed} onChange={setTyped} />
      <label className={label}>Owner e-mail
        <input className={field} type="email" value={owner} onChange={(e) => setOwner(e.target.value)} />
      </label>
      {LINKS_LICENCE.includes(type) && (
        <label className={label}>Licence it limits
          <select className={field} value={licenseId} onChange={(e) => setLicenseId(e.target.value)}>
            <option value="">Not linked</option>
            {licenses.map((l) => <option key={l.id} value={l.id}>{l.app_name}</option>)}
          </select>
        </label>
      )}
      <label className={label}>Due date (optional)
        <input className={field} type="date" value={due} onChange={(e) => setDue(e.target.value)} />
      </label>
      <label className={`${label} sm:col-span-2 lg:col-span-4`}>Clause (optional)
        <textarea className={`${field} h-16 py-2`} value={clause} onChange={(e) => setClause(e.target.value)} />
      </label>
      <div className="flex items-center gap-3 sm:col-span-2 lg:col-span-4">
        <Button type="submit" loading={busy}>Add obligation</Button>
        {error && <p role="alert" className="text-13 text-danger-600">{error}</p>}
      </div>
    </form>
  );
}

/** The contract page's obligations card. */
export function ObligationActions({ contractId, data, licenses, onChanged }: {
  contractId: string; data: ContractObligations; licenses: LicenseItem[]; onChanged: () => void;
}) {
  const { user } = useAuth();
  const canSettle = SETTLE.includes(user?.role ?? "");
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const toConfirm = data.obligations.filter((o) => o.status === "to_confirm").length;

  const reread = async () => {
    setBusy(true);
    setNote(null);
    try {
      const res = await contractsApi.rereadObligations(contractId);
      setNote(res.data.added.length ? `Added: ${res.data.added.join(", ").replace(/_/g, " ")}.` : "Nothing new found.");
      onChanged();
    } catch (err) {
      setNote(message(err, "Unable to read the contract again."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Obligations"
        subtitle={data.reading ? "Reading the signed contract for its obligations…"
          : toConfirm ? `${toConfirm} read from the contract and waiting to be confirmed. Nothing is tracked until it is.`
          : "What this contract commits both sides to after signature. Owners are reminded before each due date."}
        action={canSettle && !data.reading && (
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" loading={busy} onClick={reread}>Read again</Button>
            <Button size="sm" variant="secondary" onClick={() => setAdding(!adding)}>{adding ? "Close" : "Add by hand"}</Button>
          </div>
        )}
      />
      <CardBody>
        {data.obligations.length === 0 ? (
          <p className="text-13 text-ink-3">{data.reading ? "This takes up to a minute after signing." : "No obligations found in this contract."}</p>
        ) : (
          <ul className="flex flex-col">
            {data.obligations.map((ob) => <ObligationRow key={ob.id} ob={ob} licenses={licenses} onChanged={onChanged} />)}
          </ul>
        )}
        {data.credits.length > 0 && <Credits credits={data.credits} onChanged={onChanged} />}
        {adding && <AddObligation contractId={contractId} licenses={licenses} onDone={() => { setAdding(false); onChanged(); }} />}
        {note && <p role="status" className="mt-2 text-13 text-ink-2">{note}</p>}
      </CardBody>
    </Card>
  );
}
