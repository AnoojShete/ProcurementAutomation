import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { budgetsApi } from "@/api/budgets";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { formatCurrency } from "@/lib/format";
import type { Budget, BudgetCategory, BudgetInput, BudgetPeriod } from "@/types/api";

/** Every budget action (finance and admin): create one budget, import many
 * from CSV, and on a budget's own page change its amount or owner, or delete
 * it while nothing draws on it. Calls only the approval agent's API. */

const CATEGORIES: { value: BudgetCategory; label: string }[] = [
  { value: "hardware", label: "Hardware" },
  { value: "software", label: "Software licences" },
  { value: "saas", label: "SaaS" },
  { value: "services", label: "IT services" },
];

const field = "h-9 w-full rounded border border-rule-strong bg-sheet px-2.5 text-sm text-ink focus:border-accent";
const label = "flex flex-col gap-1 text-13 text-ink-2";

function message(e: unknown, fallback: string) {
  return e instanceof ApiError ? e.message : fallback;
}

function CreateBudget({ period, onChanged }: { period: BudgetPeriod; onChanged: () => void }) {
  const [form, setForm] = useState({ department: "", category: "hardware" as BudgetCategory, amount: "", owner: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setDone(null);
    const amount = Number(form.amount);
    if (!form.department.trim() || !Number.isFinite(amount) || amount < 0) {
      setError("Enter a department and an amount of zero or more.");
      return;
    }
    setBusy(true);
    try {
      const res = await budgetsApi.create({
        department: form.department.trim(), category: form.category, amount_inr: amount,
        fiscal_year: period.fiscal_year, period: period.period, owner_email: form.owner.trim() || null,
      });
      setDone(`${res.data.department} ${res.data.category}: ${formatCurrency(res.data.amount_inr)} for ${res.data.period} ${res.data.fiscal_year}.`);
      setForm({ ...form, department: "", amount: "", owner: "" });
      onChanged();
    } catch (err) {
      setError(message(err, "Unable to create the budget."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5 lg:items-end">
      <label className={label}>Department
        <input className={field} value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} placeholder="Engineering" />
      </label>
      <label className={label}>Category
        <select className={field} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as BudgetCategory })}>
          {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      </label>
      <label className={label}>Amount (₹)
        <input className={field} inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} placeholder="500000" />
      </label>
      <label className={label}>Owner e-mail (optional)
        <input className={field} type="email" value={form.owner} onChange={(e) => setForm({ ...form, owner: e.target.value })} />
      </label>
      <Button type="submit" loading={busy}>Add budget for {period.period} {period.fiscal_year}</Button>
      {error && <p role="alert" className="text-13 text-danger-600 sm:col-span-2 lg:col-span-5">{error}</p>}
      {done && <p role="status" className="text-13 text-success-700 sm:col-span-2 lg:col-span-5">Added: {done}</p>}
    </form>
  );
}

/** "department,category,amount[,owner_email]" per line; a header line is skipped. */
export function parseBudgetCsv(text: string, period: BudgetPeriod): { rows: BudgetInput[]; errors: string[] } {
  const rows: BudgetInput[] = [];
  const errors: string[] = [];
  const known = new Set(CATEGORIES.map((c) => c.value));
  text.split(/\r?\n/).forEach((raw, i) => {
    const line = raw.trim();
    if (!line || (i === 0 && /department/i.test(line))) return;
    const [department, category, amount, owner] = line.split(",").map((c) => c.trim());
    const value = Number(amount);
    if (!department || !known.has(category as BudgetCategory) || !Number.isFinite(value) || value < 0) {
      errors.push(`Line ${i + 1}: "${line}"`);
      return;
    }
    rows.push({ department, category: category as BudgetCategory, amount_inr: value, owner_email: owner || null,
                fiscal_year: period.fiscal_year, period: period.period });
  });
  return { rows, errors };
}

function ImportBudgets({ period, onChanged }: { period: BudgetPeriod; onChanged: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    setDone(null);
    const { rows, errors } = parseBudgetCsv(text, period);
    if (errors.length) {
      setError(`Fix these lines first (category is hardware, software, saas or services): ${errors.slice(0, 3).join("; ")}`);
      return;
    }
    if (!rows.length) {
      setError("Paste at least one line.");
      return;
    }
    setBusy(true);
    try {
      const res = await budgetsApi.importRows(rows);
      setDone(`${res.data.created} created, ${res.data.updated} updated.`);
      setText("");
      onChanged();
    } catch (err) {
      setError(message(err, "Unable to import the budgets."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <label className={label}>
        Paste CSV: department, category, amount, owner e-mail (optional), one budget per line, for {period.period} {period.fiscal_year}
        <textarea className={`${field} h-28 py-2 font-mono text-13`} value={text} onChange={(e) => setText(e.target.value)}
          placeholder={"department,category,amount,owner_email\nEngineering,saas,600000,cto@acme.test\nEngineering,hardware,1500000"} />
      </label>
      <div className="flex items-center gap-3">
        <Button variant="secondary" onClick={submit} loading={busy}>Import</Button>
        {error && <p role="alert" className="text-13 text-danger-600">{error}</p>}
        {done && <p role="status" className="text-13 text-success-700">{done}</p>}
      </div>
    </div>
  );
}

/** The budgets list page's action panel. */
export function BudgetPlanningActions({ period, onChanged }: { period: BudgetPeriod; onChanged: () => void }) {
  const [mode, setMode] = useState<"one" | "import">("one");
  return (
    <Card>
      <CardHeader
        title="Set budgets"
        subtitle="A request is checked against its department's budget for its category and period."
        action={
          <div className="flex gap-1" role="tablist" aria-label="How to add budgets">
            <Button size="sm" variant={mode === "one" ? "secondary" : "ghost"} role="tab" aria-selected={mode === "one"} onClick={() => setMode("one")}>One budget</Button>
            <Button size="sm" variant={mode === "import" ? "secondary" : "ghost"} role="tab" aria-selected={mode === "import"} onClick={() => setMode("import")}>Import CSV</Button>
          </div>
        }
      />
      <CardBody>
        {mode === "one" ? <CreateBudget period={period} onChanged={onChanged} /> : <ImportBudgets period={period} onChanged={onChanged} />}
      </CardBody>
    </Card>
  );
}

/** A budget's own page: change the amount or owner; delete while unused. */
export function BudgetEditActions({ budget, inUse, onChanged }: { budget: Budget; inUse: boolean; onChanged: () => void }) {
  const navigate = useNavigate();
  const [amount, setAmount] = useState(String(budget.amount_inr));
  const [owner, setOwner] = useState(budget.owner_email ?? "");
  const [busy, setBusy] = useState<"save" | "delete" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setDone(null);
    const value = Number(amount);
    if (!Number.isFinite(value) || value < 0) {
      setError("Enter an amount of zero or more.");
      return;
    }
    setBusy("save");
    try {
      await budgetsApi.update(budget.id, { amount_inr: value, owner_email: owner.trim() });
      setDone("Saved.");
      onChanged();
    } catch (err) {
      setError(message(err, "Unable to save the budget."));
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete the ${budget.department} ${budget.category} budget for ${budget.period} ${budget.fiscal_year}?`)) return;
    setError(null);
    setBusy("delete");
    try {
      await budgetsApi.remove(budget.id);
      navigate("/app/budgets");
    } catch (err) {
      setError(message(err, "Unable to delete the budget."));
      setBusy(null);
    }
  };

  return (
    <Card>
      <CardHeader title="Change this budget" subtitle="Every change is recorded in the audit log." />
      <CardBody>
        <form onSubmit={save} className="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:items-end">
          <label className={label}>Amount (₹)
            <input className={field} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label className={label}>Owner e-mail
            <input className={field} type="email" value={owner} onChange={(e) => setOwner(e.target.value)} />
          </label>
          <div className="flex gap-2">
            <Button type="submit" loading={busy === "save"}>Save</Button>
            <Button type="button" variant="destructive" loading={busy === "delete"} disabled={inUse}
              title={inUse ? "Requests draw on this budget; change its amount instead" : undefined} onClick={remove}>
              Delete
            </Button>
          </div>
          {error && <p role="alert" className="text-13 text-danger-600 sm:col-span-3">{error}</p>}
          {done && <p role="status" className="text-13 text-success-700 sm:col-span-3">{done}</p>}
        </form>
      </CardBody>
    </Card>
  );
}
